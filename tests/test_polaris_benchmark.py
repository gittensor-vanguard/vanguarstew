"""Contract tests for the receipt-bound dual-target benchmark seal."""

import base64
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.polaris import (  # noqa: E402
    POLARIS_ATTEST_BASE_URL,
    expected_report_data,
    workload_bound_digest,
)
from benchmark.polaris_benchmark import (  # noqa: E402
    POLARIS_BENCHMARK_SEAL_CONTRACT,
    PolarisBenchmarkClient,
    PolarisBenchmarkError,
    PolarisBenchmarkSealPlan,
    validate_benchmark_report,
    verify_benchmark_seal,
)
from scripts.run_polaris_benchmark import run as run_benchmark_seal  # noqa: E402
from scripts.score_pr_delta import combine_dual_target  # noqa: E402
from scripts.verify_polaris_benchmark import run as verify_benchmark_seal_cli  # noqa: E402

NONCE = "ab" * 32
PUBKEY = base64.b64encode(b"fresh-benchmark-requester").decode()
BASE_SHA = "12" * 20
HEAD_SHA = "34" * 20


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


def _target(band, *, reason="target result"):
    return {
        "band": band,
        "blocks_merge": band == "blocked",
        "label": None if band in {"blocked", "none"} else f"perf:{band}",
        "multiplier": {"xs": 0.5, "s": 1.0, "m": 1.5, "l": 2.5, "xl": 4.0}.get(band),
        "reason": reason,
    }


def _report(*, padding=""):
    report = combine_dual_target(_target("s"), _target("xs"))
    report.update(
        {
            "pr_number": 2042,
            "base_ref": "test",
            "base_sha": BASE_SHA,
            "head_sha": HEAD_SHA,
        }
    )
    if padding:
        report["padding"] = padding
    report["evidence"] = build_evidence(
        report,
        {
            "repo_set": "public+second-target",
            "repo_set_partition": "tuned",
            "seed": 0,
            "rotation_seed": None,
            "model": "model-snapshot",
            "agent_commit": HEAD_SHA,
            "eval_image": None,
            "transcript_digest": "56" * 32,
        },
    )
    return report


def _plan(report=None):
    return PolarisBenchmarkSealPlan(
        report=_report() if report is None else report,
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
    )


def _receipt(plan=None, **overrides):
    plan = plan or _plan()
    raw_quote = bytearray(632)
    raw_quote[568:632] = expected_report_data(
        NONCE,
        PUBKEY,
        workload_bound_digest(plan.workload),
        plan.stdout,
        files_sha256=plan.files_sha256,
    )
    response = {
        "tee_attestation": {
            "quote_b64": base64.b64encode(raw_quote).decode(),
            "bound_digest": workload_bound_digest(plan.workload),
            "binding_version": 2,
            "files_sha256": plan.files_sha256,
            "collateral_b64": "Y29sbGF0ZXJhbA==",
        },
        "verification": {"intel_verified": True},
        "stdout": plan.stdout,
        "cost_usd": 0.01,
    }
    response.update(overrides)
    return response


def _write_report(path, report=None):
    path.write_text(json.dumps(_report() if report is None else report), encoding="utf-8")
    path.chmod(0o600)


def test_plan_validates_report_evidence_and_emits_only_fixed_decision():
    plan = _plan()
    output = json.loads(plan.stdout)
    assert output == {
        "band": "xs",
        "challenge": NONCE,
        "contract": POLARIS_BENCHMARK_SEAL_CONTRACT,
        "evidence_report_data": _report()["evidence"]["report_data"],
        "report_sha256": plan.report_sha256,
    }
    assert plan.request_body()["egress"] == "none"
    assert "image" not in plan.request_body()
    assert set(plan.request_body()["files"]) == {"/submission/report.part00"}
    assert "2042" not in plan.workload
    assert BASE_SHA not in plan.workload
    assert HEAD_SHA not in plan.workload
    summary = plan.approval_summary()
    assert summary["network_request_made"] is False
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["claim_boundary"]["hosted_model_inference_inside_tee"] is False


def test_large_report_is_split_across_bounded_mounted_files():
    plan = _plan(_report(padding="x" * 300_000))
    assert len(plan.files) == 2
    assert all(len(part) <= 256 * 1024 for part in plan.files.values())
    assert b"".join(plan.files[path] for path in sorted(plan.files))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda report: report.update(band="xl"), "decision"),
        (lambda report: report.update(head_sha="bad"), "head commit"),
        (lambda report: report["evidence"]["inputs"].update(transcript_digest=None), "evidence"),
        (lambda report: report["evidence"].update(artifact_digest="00" * 32), "evidence"),
    ],
)
def test_report_validation_fails_closed_on_inconsistent_inputs(mutate, message):
    report = _report()
    mutate(report)
    with pytest.raises(PolarisBenchmarkError, match=message):
        validate_benchmark_report(report)


def test_approved_client_posts_only_the_exact_request():
    seen = {}
    plan = _plan()

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.headers["Authorization"]
        return _Response(_receipt(plan))

    client = PolarisBenchmarkClient(
        base_url=POLARIS_ATTEST_BASE_URL,
        api_key="secret",
        opener=opener,
    )
    response = client.attest_approved(
        plan,
        approved_request_sha256=plan.request_sha256(),
    )
    assert response["stdout"] == plan.stdout
    assert seen == {
        "url": "https://polaris.computer/v1/attest",
        "method": "POST",
        "body": plan.request_body(),
        "authorization": "Bearer secret",
    }


def test_changed_approval_or_host_fails_before_network():
    plan = _plan()
    client = PolarisBenchmarkClient(
        base_url=POLARIS_ATTEST_BASE_URL,
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network must not be used"),
    )
    with pytest.raises(PolarisBenchmarkError, match="approved"):
        client.attest_approved(plan, approved_request_sha256="00" * 32)
    wrong_host = PolarisBenchmarkClient(
        base_url="https://example.invalid",
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network must not be used"),
    )
    with pytest.raises(PolarisBenchmarkError, match="documented"):
        wrong_host.attest_approved(plan, approved_request_sha256=plan.request_sha256())


def test_receipt_verifier_checks_report_files_workload_and_exact_stdout():
    plan = _plan()
    valid = verify_benchmark_seal(_receipt(plan), plan=plan)
    assert valid["ok"] is True
    assert valid["verification_level"] == "polaris-verified"
    assert valid["stdout_exact"] is True

    changed = verify_benchmark_seal(_receipt(plan, stdout="changed"), plan=plan)
    assert changed["ok"] is False
    assert changed["stdout_exact"] is False


def test_live_runner_saves_receipt_privately_and_prints_only_summary(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    _write_report(report_path)
    plan = _plan()

    def factory(path, *, base_url):
        assert path == "private.env"
        return PolarisBenchmarkClient(
            base_url=base_url,
            api_key="secret",
            opener=lambda *args, **kwargs: _Response(_receipt(plan)),
        )

    status = run_benchmark_seal(
        [
            "--env-file",
            "private.env",
            "--report",
            str(report_path),
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--approved-request-sha256",
            plan.request_sha256(),
            "--receipt-output",
            str(receipt_path),
        ],
        client_factory=factory,
    )
    assert status == 0
    assert json.loads(receipt_path.read_text())["stdout"] == plan.stdout
    if os.name != "nt":
        assert receipt_path.stat().st_mode & 0o777 == 0o600
    summary = json.loads(capsys.readouterr().out)
    assert summary == {
        "ok": True,
        "receipt_saved": True,
        "request_sha256": plan.request_sha256(),
        "verification_level": "polaris-verified",
    }
    rendered = json.dumps(summary)
    assert "secret" not in rendered
    assert "2042" not in rendered
    assert BASE_SHA not in rendered
    assert HEAD_SHA not in rendered


def test_live_runner_refuses_broad_report_permissions_and_existing_receipt(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    _write_report(report_path)
    report_path.chmod(0o644)
    status = run_benchmark_seal(
        [
            "--env-file",
            "private.env",
            "--report",
            str(report_path),
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--approved-request-sha256",
            "00" * 32,
            "--receipt-output",
            str(receipt_path),
        ],
        client_factory=lambda *args, **kwargs: pytest.fail("client must not be created"),
    )
    assert status == 2
    assert not receipt_path.exists()
    assert capsys.readouterr().err == "benchmark seal failed\n"

    report_path.chmod(0o600)
    receipt_path.write_text("keep", encoding="utf-8")
    plan = _plan()
    status = run_benchmark_seal(
        [
            "--env-file",
            "private.env",
            "--report",
            str(report_path),
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--approved-request-sha256",
            plan.request_sha256(),
            "--receipt-output",
            str(receipt_path),
        ],
        client_factory=lambda *args, **kwargs: pytest.fail("client must not be created"),
    )
    assert status == 2
    assert receipt_path.read_text() == "keep"


def test_verifier_cli_rechecks_private_receipt_without_rendering_context(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    receipt_path = tmp_path / "receipt.json"
    _write_report(report_path)
    plan = _plan()
    receipt_path.write_text(json.dumps(_receipt(plan)), encoding="utf-8")
    receipt_path.chmod(0o600)
    status = verify_benchmark_seal_cli(
        [
            "--receipt",
            str(receipt_path),
            "--report",
            str(report_path),
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
        ]
    )
    assert status == 0
    rendered = capsys.readouterr().out
    assert json.loads(rendered)["verification_level"] == "polaris-verified"
    assert "2042" not in rendered
    assert BASE_SHA not in rendered
    assert HEAD_SHA not in rendered
