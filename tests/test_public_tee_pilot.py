"""End-to-end contract tests for the fixed public Polaris TEE pilot."""

import base64
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.polaris import (  # noqa: E402
    POLARIS_ATTEST_BASE_URL,
    PUBLIC_TEE_PILOT_INPUT,
    PUBLIC_TEE_PILOT_INPUT_PATH,
    PUBLIC_TEE_PILOT_STDOUT,
    PUBLIC_TEE_PILOT_WORKLOAD,
    PolarisClient,
    PolarisError,
    PublicTeePilotPlan,
    expected_report_data,
    verify_public_tee_pilot,
    workload_bound_digest,
)
from scripts.plan_public_tee_pilot import build_plan  # noqa: E402
from scripts.run_public_tee_pilot import run as run_pilot  # noqa: E402
from scripts.verify_public_tee_pilot import run as verify_pilot  # noqa: E402

NONCE = "ab" * 32
PUBKEY = base64.b64encode(b"fresh-public-pilot-requester").decode()


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


def _plan():
    return PublicTeePilotPlan(nonce=NONCE, e2e_pubkey_b64=PUBKEY)


def _receipt(**overrides):
    plan = _plan()
    raw_quote = bytearray(632)
    raw_quote[568:632] = expected_report_data(
        NONCE,
        PUBKEY,
        workload_bound_digest(PUBLIC_TEE_PILOT_WORKLOAD),
        PUBLIC_TEE_PILOT_STDOUT,
        files_sha256=plan.files_sha256(),
    )
    response = {
        "tee_attestation": {
            "quote_b64": base64.b64encode(raw_quote).decode(),
            "bound_digest": workload_bound_digest(PUBLIC_TEE_PILOT_WORKLOAD),
            "binding_version": 2,
            "files_sha256": plan.files_sha256(),
            "collateral_b64": "Y29sbGF0ZXJhbA==",
        },
        "verification": {"intel_verified": True},
        "stdout": PUBLIC_TEE_PILOT_STDOUT,
        "cost_usd": 0.01,
    }
    response.update(overrides)
    return response


def test_plan_fixes_public_code_input_output_and_no_egress():
    plan = _plan()
    body = plan.request_body()
    assert body == {
        "nonce": NONCE,
        "e2e_pubkey_b64": PUBKEY,
        "workload": PUBLIC_TEE_PILOT_WORKLOAD,
        "egress": "none",
        "files": {
            PUBLIC_TEE_PILOT_INPUT_PATH: base64.b64encode(PUBLIC_TEE_PILOT_INPUT).decode()
        },
    }
    assert "image" not in body
    summary = plan.approval_summary()
    assert summary["network_request_made"] is False
    assert summary["endpoint"] == "https://polaris.computer/v1/attest"
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["claim_boundary"] == {
        "execution_integrity": True,
        "workload_confidentiality": False,
        "gpu_provenance": False,
    }


def test_planner_requires_fresh_well_formed_binding_values():
    assert build_plan(["--nonce", NONCE, "--e2e-pubkey", PUBKEY]) == _plan()
    with pytest.raises(PolarisError):
        PublicTeePilotPlan(nonce="short", e2e_pubkey_b64=PUBKEY)
    with pytest.raises(PolarisError):
        PublicTeePilotPlan(nonce=NONCE, e2e_pubkey_b64="not-base64")


def test_approved_client_posts_only_the_exact_public_request():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.headers["Authorization"]
        return _Response(_receipt())

    plan = _plan()
    client = PolarisClient(
        base_url=POLARIS_ATTEST_BASE_URL,
        api_key="secret",
        opener=opener,
    )
    result = client.attest_public_pilot_approved(
        plan,
        approved_request_sha256=plan.request_sha256(),
    )
    assert result["stdout"] == PUBLIC_TEE_PILOT_STDOUT
    assert seen == {
        "url": "https://polaris.computer/v1/attest",
        "method": "POST",
        "body": plan.request_body(),
        "authorization": "Bearer secret",
    }


def test_changed_or_missing_approval_fails_before_network():
    client = PolarisClient(
        base_url=POLARIS_ATTEST_BASE_URL,
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )
    with pytest.raises(PolarisError, match="approved"):
        client.attest_public_pilot_approved(
            _plan(),
            approved_request_sha256="00" * 32,
        )


def test_approved_pilot_refuses_a_different_api_host_before_network():
    client = PolarisClient(
        base_url="https://example.invalid",
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )
    plan = _plan()
    with pytest.raises(PolarisError, match="documented"):
        client.attest_public_pilot_approved(
            plan,
            approved_request_sha256=plan.request_sha256(),
        )


def test_receipt_verifier_checks_the_complete_public_contract():
    report = verify_public_tee_pilot(_receipt(), plan=_plan())
    assert report["ok"] is True
    assert report["outer"]["verification_level"] == "polaris-verified"
    assert report["outer"]["hardware_attested"] is False
    assert report["outer"]["hardware_attestation_claimed"] is True
    assert all(report["checks"].values())


def test_receipt_verifier_rejects_changed_output_and_wrong_challenge():
    changed = verify_public_tee_pilot(_receipt(stdout="changed\n"), plan=_plan())
    assert changed["ok"] is False
    assert changed["checks"]["receipt_contract"] is False
    wrong_plan = PublicTeePilotPlan(nonce="cd" * 32, e2e_pubkey_b64=PUBKEY)
    wrong = verify_public_tee_pilot(_receipt(), plan=wrong_plan)
    assert wrong["ok"] is False
    assert wrong["outer"]["checks"]["caller_binding"] is False


def test_live_runner_saves_full_receipt_mode_0600_and_prints_only_summary(tmp_path, capsys):
    plan = _plan()

    def factory(path, *, base_url):
        assert path == "private.env"
        assert base_url == POLARIS_ATTEST_BASE_URL
        return PolarisClient(base_url=base_url, api_key="secret", opener=lambda *a, **k: _Response(_receipt()))

    output = tmp_path / "receipt.json"
    status = run_pilot(
        [
            "--env-file",
            "private.env",
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--approved-request-sha256",
            plan.request_sha256(),
            "--receipt-output",
            str(output),
        ],
        client_factory=factory,
    )
    assert status == 0
    assert json.loads(output.read_text())["stdout"] == PUBLIC_TEE_PILOT_STDOUT
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600
    rendered = json.loads(capsys.readouterr().out)
    assert rendered == {
        "ok": True,
        "receipt_saved": True,
        "request_sha256": plan.request_sha256(),
        "verification_level": "polaris-verified",
    }
    assert "secret" not in json.dumps(rendered)


def test_live_runner_refuses_to_overwrite_a_receipt(tmp_path, capsys):
    output = tmp_path / "receipt.json"
    output.write_text("keep", encoding="utf-8")
    plan = _plan()

    def factory(path, *, base_url):
        pytest.fail("client must not be created when the output already exists")

    status = run_pilot(
        [
            "--env-file",
            "private.env",
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--approved-request-sha256",
            plan.request_sha256(),
            "--receipt-output",
            str(output),
        ],
        client_factory=factory,
    )
    assert status == 2
    assert output.read_text(encoding="utf-8") == "keep"
    assert capsys.readouterr().err == "public TEE pilot failed\n"


def test_verifier_cli_accepts_a_valid_saved_receipt(tmp_path, capsys):
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(_receipt()), encoding="utf-8")
    status = verify_pilot(
        [
            "--receipt",
            str(receipt),
            "--nonce",
            NONCE,
            "--e2e-pubkey",
            PUBKEY,
            "--strict",
        ]
    )
    captured = capsys.readouterr()
    assert status == 0
    assert json.loads(captured.out)["ok"] is True
    assert "OK (polaris-verified)" in captured.err
