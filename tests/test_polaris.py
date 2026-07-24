"""Contract tests for the Polaris outer quote + vanguarstew inner evidence chain."""

import base64
import hashlib
import io
import json
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.intel_dcap import IntelVerificationResult  # noqa: E402
from benchmark.polaris import (  # noqa: E402
    PolarisClient,
    PolarisError,
    PolarisReceipt,
    build_stdout_envelope,
    expected_report_data,
    mounted_files_sha256,
    verify_attested_envelope,
    verify_receipt,
)

NONCE = "ab" * 32
PUBKEY = base64.b64encode(b"requester-key-material").decode()
IMAGE_HEX = "12" * 32
IMAGE = f"ghcr.io/gittensor-vanguard/vanguarstew-eval@sha256:{IMAGE_HEX}"
RESOLVED = f"sha256:{IMAGE_HEX}"
ARTIFACT = {"composite_mean": 0.62, "composite_parts": {"judge_mean": 0.6}}
FILES_SHA = "34" * 32
EGRESS_SHA = "56" * 32


def _quote(
    stdout: str,
    nonce: str = NONCE,
    pubkey: str = PUBKEY,
    image_digest: str = RESOLVED,
    *,
    files_sha256: str = "",
    egress_log_sha256: str = "",
) -> str:
    raw = bytearray(632)
    raw[568:632] = expected_report_data(
        nonce,
        pubkey,
        image_digest,
        stdout,
        files_sha256=files_sha256,
        egress_log_sha256=egress_log_sha256,
    )
    return base64.b64encode(raw).decode()


def _receipt(stdout="result", **overrides):
    values = {
        "quote_b64": _quote(stdout),
        "intel_verified": True,
        "image_digest": RESOLVED,
        "stdout": stdout,
        "cost_usd": 0.12,
        "stub": False,
    }
    values.update(overrides)
    return values


def _envelope_receipt(**overrides):
    evidence = build_evidence(
        ARTIFACT,
        {
            "repo_set": "curated",
            "seed": 0,
            "model": "model@snapshot",
            "agent_commit": "abc",
            "eval_image": RESOLVED,
            "transcript_digest": "34" * 32,
        },
    )
    stdout = build_stdout_envelope(ARTIFACT, evidence)
    return _receipt(stdout, **overrides)


def test_report_data_uses_the_documented_two_half_recipe():
    stdout = "canonical output"
    report_data = expected_report_data(NONCE, PUBKEY, RESOLVED, stdout)
    assert len(report_data) == 64
    assert report_data[:32] == hashlib.sha256((NONCE + PUBKEY).encode()).digest()
    stdout_hex = hashlib.sha256(stdout.encode()).hexdigest()
    assert report_data[32:] == hashlib.sha256((RESOLVED + stdout_hex).encode()).digest()


def test_report_data_v2_appends_egress_then_files_digests():
    stdout = "canonical output"
    report_data = expected_report_data(
        NONCE,
        PUBKEY,
        RESOLVED,
        stdout,
        egress_log_sha256=EGRESS_SHA,
        files_sha256=FILES_SHA,
    )
    stdout_hex = hashlib.sha256(stdout.encode()).hexdigest()
    assert report_data[32:] == hashlib.sha256(
        (RESOLVED + stdout_hex + EGRESS_SHA + FILES_SHA).encode()
    ).digest()


def test_mounted_files_digest_uses_sorted_tab_separated_rows_with_final_newline():
    files = {
        "/submission/zeta.txt": b"vanguarstew-polaris-v2-zeta\n",
        "/submission/alpha.txt": b"vanguarstew-polaris-v2-alpha\n",
    }
    assert mounted_files_sha256(files) == (
        "7267c7a68e4f2df42b749881792ddfb6ff900fd46d871afeaa17ad93dec2b955"
    )
    assert mounted_files_sha256(dict(reversed(list(files.items())))) == mounted_files_sha256(files)
    assert mounted_files_sha256(None) == ""


def test_valid_live_receipt_is_polaris_verified_but_not_independently_verified():
    report = verify_receipt(_receipt(), nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE)
    assert report["ok"] is True
    assert report["verification_level"] == "polaris-verified"
    assert report["hardware_attested"] is False
    assert report["hardware_attestation_claimed"] is True
    assert report["independent_intel_verified"] is None


def test_current_service_response_fields_are_preserved():
    receipt = PolarisReceipt.from_response(
        {
            "tee_attestation": {
                "quote_b64": _quote("result"),
                "bound_digest": RESOLVED,
                "collateral_b64": "Y29sbGF0ZXJhbA==",
                "binding_version": 2,
                "files_sha256": FILES_SHA,
            },
            "verification": {"intel_verified": True},
            "stdout": "result",
        }
    )
    assert receipt.image_digest == RESOLVED
    assert receipt.collateral == "Y29sbGF0ZXJhbA=="
    assert receipt.binding_version == 2
    assert receipt.files_sha256 == FILES_SHA
    assert receipt.egress_log_sha256 == ""


def test_binding_v2_requires_and_checks_an_independent_files_digest():
    receipt = _receipt(
        quote_b64=_quote("result", files_sha256=FILES_SHA),
        binding_version=2,
        files_sha256=FILES_SHA,
    )
    missing = verify_receipt(
        receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert missing["ok"] is False
    assert missing["checks"]["result_binding"] is True
    assert missing["checks"]["expected_files_digest"] is False

    wrong = verify_receipt(
        receipt,
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        expected_image=IMAGE,
        expected_files_sha256="78" * 32,
    )
    assert wrong["ok"] is False
    assert wrong["checks"]["expected_files_digest"] is False

    valid = verify_receipt(
        receipt,
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        expected_image=IMAGE,
        expected_files_sha256=FILES_SHA,
    )
    assert valid["ok"] is True
    assert valid["checks"]["binding_version"] is True
    assert valid["checks"]["expected_files_digest"] is True

    malformed = verify_receipt(
        receipt,
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        expected_image=IMAGE,
        expected_files_sha256=123,
    )
    assert malformed["ok"] is False
    assert malformed["checks"]["expected_files_digest"] is False


@pytest.mark.parametrize("field", ["files_sha256", "egress_log_sha256"])
def test_receipt_rejects_non_string_binding_digests(field):
    receipt = _receipt()
    receipt[field] = None
    with pytest.raises(PolarisError, match="malformed binding digests"):
        PolarisReceipt.from_dict(receipt)


def test_unexpected_recorded_egress_fails_closed():
    receipt = _receipt(
        quote_b64=_quote("result", egress_log_sha256=EGRESS_SHA),
        binding_version=2,
        egress_log_sha256=EGRESS_SHA,
    )
    denied = verify_receipt(
        receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert denied["ok"] is False
    assert denied["checks"]["expected_egress_digest"] is False

    accepted = verify_receipt(
        receipt,
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        expected_image=IMAGE,
        expected_egress_log_sha256=EGRESS_SHA,
    )
    assert accepted["ok"] is True


@pytest.mark.parametrize(
    "change,failed",
    [
        ({"nonce": "cd" * 32}, "caller_binding"),
        ({"pubkey": base64.b64encode(b"different-key").decode()}, "caller_binding"),
        ({"receipt": {"stdout": "changed"}}, "result_binding"),
        ({"image": f"name@sha256:{'ef' * 32}"}, "image_digest"),
    ],
)
def test_any_changed_bound_value_fails(change, failed):
    receipt = _receipt()
    receipt.update(change.get("receipt", {}))
    report = verify_receipt(
        receipt,
        nonce=change.get("nonce", NONCE),
        e2e_pubkey_b64=change.get("pubkey", PUBKEY),
        expected_image=change.get("image", IMAGE),
    )
    assert report["ok"] is False
    assert report["checks"][failed] is False


def test_mutable_expected_image_tag_fails_closed():
    report = verify_receipt(
        _receipt(), nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image="ghcr.io/org/eval:latest"
    )
    assert report["ok"] is False
    assert report["checks"]["expected_image_pinned"] is False


def test_short_quote_and_negative_server_verification_fail_closed():
    short = _receipt(quote_b64=base64.b64encode(b"short").decode())
    assert (
        verify_receipt(short, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE)["checks"][
            "quote_structure"
        ]
        is False
    )
    denied = _receipt(intel_verified=False)
    report = verify_receipt(denied, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE)
    assert report["ok"] is False
    assert report["checks"]["polaris_intel_verified"] is False


def test_stub_never_counts_as_hardware_attestation():
    receipt = _receipt(stub=True)
    strict = verify_receipt(receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE)
    assert strict["ok"] is False
    dev = verify_receipt(
        receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE, require_live=False
    )
    assert dev["ok"] is True
    assert dev["verification_level"] == "stub"
    assert dev["hardware_attested"] is False


def test_structured_local_verifier_is_required_for_independent_claim():
    seen = {}

    def verifier(quote, collateral):
        seen["quote"] = quote
        seen["collateral"] = collateral
        return IntelVerificationResult(
            chain_verified=True,
            tcb_accepted=True,
            measurements_verified=True,
            backend="fixture-dcap",
            policy_digest="ab" * 32,
            tcb_status="UpToDate",
            detail="fixture verified",
        )

    receipt = _receipt(collateral={"tcb": "fixture"})
    report = verify_receipt(
        receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE, intel_verifier=verifier
    )
    assert report["ok"] is True
    assert report["verification_level"] == "independently-verified"
    assert report["hardware_attested"] is True
    assert report["independent_intel_verified"] is True
    assert report["checks"]["intel_tcb_policy"] is True
    assert report["checks"]["tdx_measurement_policy"] is True
    assert report["independent_verification"]["policy_digest"] == "ab" * 32
    assert len(seen["quote"]) == 632 and seen["collateral"] == {"tcb": "fixture"}


def test_legacy_boolean_callback_cannot_assert_tcb_or_measurement_policy():
    report = verify_receipt(
        _receipt(),
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        expected_image=IMAGE,
        intel_verifier=lambda quote, collateral: True,
    )
    assert report["ok"] is False
    assert report["hardware_attested"] is False
    assert report["hardware_attestation_claimed"] is True
    assert report["independent_intel_verified"] is True
    assert report["checks"]["intel_chain_local"] is True
    assert report["checks"]["intel_tcb_policy"] is False
    assert report["checks"]["tdx_measurement_policy"] is False


def test_failed_or_crashing_local_verifier_fails_closed():
    for verifier in (
        lambda quote, collateral: False,
        lambda quote, collateral: (_ for _ in ()).throw(RuntimeError("boom")),
    ):
        report = verify_receipt(
            _receipt(),
            nonce=NONCE,
            e2e_pubkey_b64=PUBKEY,
            expected_image=IMAGE,
            intel_verifier=verifier,
        )
        assert report["ok"] is False
        assert report["checks"]["intel_chain_local"] is False


def test_outer_quote_and_inner_evidence_compose_without_reusing_report_data():
    receipt = _envelope_receipt()
    report = verify_attested_envelope(
        receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert report["ok"] is True
    assert (
        report["outer"]["report_data"] != json.loads(receipt["stdout"])["evidence"]["report_data"]
    )


def test_tampered_inner_artifact_fails_even_with_a_matching_outer_quote():
    receipt = _envelope_receipt()
    envelope = json.loads(receipt["stdout"])
    envelope["artifact"]["composite_mean"] = 0.99
    stdout = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    forged_outer = _receipt(stdout)
    report = verify_attested_envelope(
        forged_outer, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert report["ok"] is False
    assert report["checks"]["inner_evidence"] is False


def test_inner_evidence_must_bind_the_same_resolved_image():
    receipt = _envelope_receipt()
    envelope = json.loads(receipt["stdout"])
    envelope["evidence"]["inputs"]["eval_image"] = f"sha256:{'ef' * 32}"
    # Rebuild the outer quote so this isolates the inner image-link check.
    stdout = json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    report = verify_attested_envelope(
        _receipt(stdout), nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert report["ok"] is False
    assert report["checks"]["inner_image_binding"] is False


def test_stdout_must_be_canonical_json():
    receipt = _envelope_receipt()
    noncanonical = json.dumps(json.loads(receipt["stdout"]), indent=2)
    report = verify_attested_envelope(
        _receipt(noncanonical), nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE
    )
    assert report["ok"] is False
    assert report["checks"]["canonical_stdout"] is False


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


def test_live_client_posts_only_to_attest_and_preserves_the_quote():
    stdout = "result"
    payload = {
        "tee_attestation": {"quote_b64": _quote(stdout)},
        "verification": {"intel_verified": True},
        "image_digest": RESOLVED,
        "stdout": stdout,
        "cost_usd": 0.2,
    }
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.headers["Authorization"]
        seen["timeout"] = timeout
        return _Response(payload)

    client = PolarisClient(
        base_url="https://polaris.example", api_key="secret", timeout=9, opener=opener
    )
    receipt = client.attest(
        nonce=NONCE, e2e_pubkey_b64=PUBKEY, image=IMAGE, workload="python -m scripts.run_eval ..."
    )
    assert isinstance(receipt, PolarisReceipt)
    assert receipt.quote_b64 == payload["tee_attestation"]["quote_b64"]
    assert seen == {
        "url": "https://polaris.example/v1/attest",
        "body": {
            "nonce": NONCE,
            "e2e_pubkey_b64": PUBKEY,
            "image": IMAGE,
            "workload": "python -m scripts.run_eval ...",
            "egress": "none",
        },
        "authorization": "Bearer secret",
        "timeout": 9.0,
    }


def test_live_client_base64_encodes_bounded_submission_mounts():
    stdout = "result"
    payload = {
        "tee_attestation": {
            "quote_b64": _quote(stdout, files_sha256=FILES_SHA),
            "binding_version": 2,
            "files_sha256": FILES_SHA,
        },
        "verification": {"intel_verified": True},
        "image_digest": RESOLVED,
        "stdout": stdout,
    }
    seen = {}

    def opener(request, timeout):
        seen.update(json.loads(request.data))
        return _Response(payload)

    client = PolarisClient(base_url="https://polaris.example", api_key="secret", opener=opener)
    receipt = client.attest(
        nonce=NONCE,
        e2e_pubkey_b64=PUBKEY,
        image=IMAGE,
        workload="run",
        files={"/submission/input.part00": b"public-input"},
    )
    assert seen["files"] == {
        "/submission/input.part00": base64.b64encode(b"public-input").decode()
    }
    assert receipt.binding_version == 2
    assert receipt.files_sha256 == FILES_SHA


@pytest.mark.parametrize(
    "files,error",
    [
        ({f"/submission/{index}": b"x" for index in range(9)}, "at most"),
        ({"relative": b"x"}, "normalized"),
        ({"/submission/../escape": b"x"}, "normalized"),
        ({"/submission/input": "not-bytes"}, "must be bytes"),
        ({"/submission/input": b"x" * (256 * 1024 + 1)}, "must not exceed"),
    ],
)
def test_live_client_rejects_invalid_mounts_before_request(files, error):
    client = PolarisClient(
        base_url="https://polaris.example",
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )
    with pytest.raises(PolarisError, match=error):
        client.attest(
            nonce=NONCE,
            e2e_pubkey_b64=PUBKEY,
            image=IMAGE,
            workload="run",
            files=files,
        )


def test_client_refuses_implicit_insecure_or_mutable_live_calls():
    with pytest.raises(PolarisError, match="https"):
        PolarisClient(base_url="http://polaris.example", api_key="secret")
    client = PolarisClient(
        base_url="https://polaris.example", api_key="secret", opener=lambda *a, **k: io.BytesIO()
    )
    with pytest.raises(PolarisError, match="pinned"):
        client.attest(
            nonce=NONCE, e2e_pubkey_b64=PUBKEY, image="ghcr.io/org/eval:latest", workload="run"
        )


def test_client_loads_a_restricted_env_file_without_exporting_secrets(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POLARIS_URL=https://polaris.example\nLOCAL_POLARIS_KEY=top-secret\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    client = PolarisClient.from_env_file(env_file, api_key_name="LOCAL_POLARIS_KEY")
    assert client.base_url == "https://polaris.example"
    assert client.api_key == "top-secret"
    assert "LOCAL_POLARIS_KEY" not in os.environ


def test_client_accepts_the_older_polaris_key_env_name(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POLARIS_URL=https://polaris.example\nPOLARIS_KEY=top-secret\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    client = PolarisClient.from_env_file(env_file)
    assert client.api_key == "top-secret"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_client_rejects_an_env_file_readable_by_other_users(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "POLARIS_URL=https://polaris.example\nPOLARIS_KEY=top-secret\n",
        encoding="utf-8",
    )
    env_file.chmod(0o644)
    with pytest.raises(PolarisError, match="group or others"):
        PolarisClient.from_env_file(env_file)


def test_key_check_is_a_non_attesting_get_request():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["authorization"] = request.headers["Authorization"]
        return _Response({"ok": True})

    client = PolarisClient(base_url="https://polaris.example", api_key="secret", opener=opener)
    assert client.check_key() is True
    assert seen == {
        "url": "https://api.polaris.computer/api/keys",
        "method": "GET",
        "authorization": "Bearer secret",
    }


def test_binding_version_cannot_claim_v2_without_v2_extra_digests():
    receipt = _receipt(binding_version=2)
    report = verify_receipt(receipt, nonce=NONCE, e2e_pubkey_b64=PUBKEY, expected_image=IMAGE)
    assert report["ok"] is False
    assert report["checks"]["binding_version"] is False
