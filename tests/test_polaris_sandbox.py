"""Privacy and transport tests for the persistent Polaris TDX sandbox adapter."""

import base64
import hashlib
import io
import json
import os
import pathlib
import struct
import sys
import urllib.error

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.polaris_sandbox import (  # noqa: E402
    POLARIS_SANDBOX_API_URL,
    PolarisSandboxClient,
    PolarisSandboxError,
    PolarisSandboxPlan,
    inspect_boot_receipt_privacy,
    verify_boot_receipt,
)
from scripts.plan_polaris_sandbox import build_plan  # noqa: E402


def _ssh_key(comment="operator@example.invalid"):
    key_type = b"ssh-ed25519"
    key_bytes = bytes(range(32))
    wire = (
        struct.pack(">I", len(key_type)) + key_type + struct.pack(">I", len(key_bytes)) + key_bytes
    )
    return f"ssh-ed25519 {base64.b64encode(wire).decode()} {comment}"


def _plan(**overrides):
    values = {
        "name": "sealed-worker-1",
        "ssh_public_key": _ssh_key(),
        "max_spend_usd": 1.0,
        "max_runtime_minutes": 60,
    }
    values.update(overrides)
    return PolarisSandboxPlan(**values)


def _boot_receipt(public_key=None, **overrides):
    normalized = " ".join((public_key or _ssh_key()).split()[:2])
    nonce = "ab" * 32
    public_key_b64 = base64.b64encode(normalized.encode()).decode()
    binding = hashlib.sha256(f"{nonce}{public_key_b64}".encode()).hexdigest()
    receipt = {
        "kind": "tdx-1.5",
        "receipt_status": "ready",
        "nonce": nonce,
        "pubkey_b64": public_key_b64,
        "quote_b64": base64.b64encode(b"synthetic-quote").decode(),
        "report_data": binding + "00" * 32,
        "binding_verified": True,
        "intel_verified": True,
        "intel_status": "verified",
        "verified": True,
        "receipt_id": "opaque",
        "receipt_url": "/opaque",
    }
    receipt.update(overrides)
    return receipt


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


def test_plan_has_only_the_documented_bare_private_shape():
    plan = _plan()
    assert plan.request_body() == {
        "name": "sealed-worker-1",
        "size": "Sealed CPU Small",
        "ssh_public_key": " ".join(_ssh_key().split()[:2]),
        "load_with": {"email": False, "agents": []},
        "primitives": {"email_address": False, "bittensor_intel": False},
        "attested_secrets": False,
        "max_spend_usd": 1.0,
        "max_runtime_minutes": 60,
        "auto_stop": True,
    }
    encoded = json.dumps(plan.request_body(), sort_keys=True)
    assert "image" not in plan.request_body()
    assert "review" not in encoded
    assert "operator@example.invalid" not in encoded


def test_approval_summary_is_network_free_and_binds_the_exact_request():
    plan = _plan()
    summary = plan.approval_summary()
    assert summary["network_request_made"] is False
    assert summary["endpoint"] == f"{POLARIS_SANDBOX_API_URL}/api/v2/sandbox"
    assert summary["request"] == plan.request_body()
    assert summary["request_sha256"] == plan.request_sha256()
    assert len(summary["request_sha256"]) == 64
    assert all(summary["privacy"].values())


@pytest.mark.parametrize(
    "name",
    [
        "purpose-worker",
        "project-worker",
        "sealed-worker-0",
        "sealed-worker-0001",
        "Uppercase",
        "path/escape",
        "-leading",
    ],
)
def test_plan_rejects_identifying_or_malformed_names(name):
    with pytest.raises(PolarisSandboxError):
        _plan(name=name)


@pytest.mark.parametrize(
    "changes",
    [
        {"ssh_public_key": "ssh-rsa AAAA"},
        {"ssh_public_key": "ssh-ed25519 not-base64"},
        {"max_spend_usd": 0.99},
        {"max_spend_usd": 1.001},
        {"max_spend_usd": float("inf")},
        {"max_runtime_minutes": 4},
        {"max_runtime_minutes": 7 * 24 * 60 + 1},
    ],
)
def test_plan_rejects_unsafe_or_out_of_bounds_values(changes):
    with pytest.raises(PolarisSandboxError):
        _plan(**changes)


def test_offline_planner_reads_only_the_public_key_and_strips_its_comment(tmp_path):
    key_path = tmp_path / "id_ed25519.pub"
    key_path.write_text(_ssh_key("identifying-comment") + "\n", encoding="utf-8")
    plan = build_plan(["--ssh-public-key-file", str(key_path)])
    assert plan.name == "sealed-worker-1"
    assert "identifying-comment" not in plan.ssh_public_key
    assert plan.approval_summary()["network_request_made"] is False


def test_create_posts_only_the_exact_digest_approved_request():
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["body"] = json.loads(request.data)
        seen["authorization"] = request.headers["Authorization"]
        seen["timeout"] = timeout
        return _Response({"id": "sandbox_123", "status": "provisioning"})

    plan = _plan()
    client = PolarisSandboxClient(
        base_url=POLARIS_SANDBOX_API_URL,
        api_key="secret",
        timeout=9,
        opener=opener,
    )
    result = client.create_approved(plan, approved_request_sha256=plan.request_sha256())
    assert result["id"] == "sandbox_123"
    assert seen == {
        "url": "https://api.polaris.computer/api/v2/sandbox",
        "method": "POST",
        "body": plan.request_body(),
        "authorization": "Bearer secret",
        "timeout": 9.0,
    }


def test_create_rejects_missing_or_changed_approval_before_network():
    client = PolarisSandboxClient(
        base_url=POLARIS_SANDBOX_API_URL,
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network request must not be sent"),
    )
    with pytest.raises(PolarisSandboxError, match="approval|approved"):
        client.create_approved(_plan(), approved_request_sha256="00" * 32)


def test_create_rejects_a_response_without_a_sandbox_id():
    plan = _plan()
    client = PolarisSandboxClient(
        base_url=POLARIS_SANDBOX_API_URL,
        api_key="secret",
        opener=lambda *args, **kwargs: _Response({"status": "provisioning"}),
    )
    with pytest.raises(PolarisSandboxError, match="missing an id"):
        client.create_approved(plan, approved_request_sha256=plan.request_sha256())


def test_detail_is_get_only_and_stop_requires_the_exact_approved_id():
    seen = []

    def opener(request, timeout):
        seen.append((request.get_method(), request.full_url, request.data))
        return _Response({"id": "sandbox_123", "status": "running"})

    client = PolarisSandboxClient(base_url=POLARIS_SANDBOX_API_URL, api_key="secret", opener=opener)
    assert client.detail("sandbox_123")["status"] == "running"
    assert client.boot_receipt("sandbox_123")["status"] == "running"
    with pytest.raises(PolarisSandboxError, match="approved"):
        client.stop_approved("sandbox_123", approved_sandbox_id="sandbox_other")
    client.stop_approved("sandbox_123", approved_sandbox_id="sandbox_123")
    assert seen == [
        ("GET", "https://api.polaris.computer/api/v2/sandbox/sandbox_123", None),
        (
            "GET",
            "https://api.polaris.computer/api/v2/compute/instances/sandbox_123/receipt",
            None,
        ),
        ("DELETE", "https://api.polaris.computer/api/v2/sandbox/sandbox_123", None),
    ]


def test_boot_receipt_independently_checks_customer_key_report_binding():
    result = verify_boot_receipt(_boot_receipt(), expected_ssh_public_key=_ssh_key())
    assert result["ok"] is True
    assert all(result["checks"].values())
    assert result["verification_level"] == "polaris-verified"
    assert result["hardware_attestation_claimed"] is True
    assert result["hardware_attested"] is False
    assert "opaque" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "unknown"},
        {"receipt_status": "pending"},
        {"quote_b64": "not-base64"},
        {"report_data": "00" * 64},
        {"binding_verified": False},
        {"intel_verified": False},
        {"verified": False},
    ],
)
def test_boot_receipt_verification_fails_closed(change):
    result = verify_boot_receipt(
        _boot_receipt(**change),
        expected_ssh_public_key=_ssh_key(),
    )
    assert result["ok"] is False
    assert result["verification_level"] == "unverified"
    assert result["hardware_attested"] is False


def test_boot_receipt_rejects_a_different_customer_key():
    key_type = b"ssh-ed25519"
    key_bytes = bytes(reversed(range(32)))
    wire = (
        struct.pack(">I", len(key_type)) + key_type + struct.pack(">I", len(key_bytes)) + key_bytes
    )
    other_key = f"ssh-ed25519 {base64.b64encode(wire).decode()}"
    result = verify_boot_receipt(_boot_receipt(), expected_ssh_public_key=other_key)
    assert result["ok"] is False
    assert result["checks"]["customer_key_encoding"] is False


def test_receipt_privacy_scan_checks_reversible_base64_without_returning_terms():
    receipt = _boot_receipt(
        opaque=base64.b64encode(b"forbidden-identity-marker").decode(),
    )
    result = inspect_boot_receipt_privacy(
        receipt,
        expected_ssh_public_key=_ssh_key(),
        forbidden_terms=["forbidden-identity-marker"],
    )
    assert result == {
        "passed": False,
        "forbidden_identifier_count": 1,
        "connection_metadata_field_count": 0,
        "customer_ssh_key_published": True,
        "unique_sandbox_key_required": True,
        "receipt_was_json_object": True,
    }
    assert "forbidden-identity-marker" not in json.dumps(result)


def test_receipt_privacy_scan_rejects_connection_fields_but_accepts_expected_key_binding():
    clean = inspect_boot_receipt_privacy(
        _boot_receipt(),
        expected_ssh_public_key=_ssh_key(),
    )
    assert clean["passed"] is True
    assert clean["customer_ssh_key_published"] is True
    exposed = inspect_boot_receipt_privacy(
        _boot_receipt(ssh_host="example.invalid"),
        expected_ssh_public_key=_ssh_key(),
    )
    assert exposed["passed"] is False
    assert exposed["connection_metadata_field_count"] == 1


def test_malformed_sandbox_id_is_rejected_before_network():
    client = PolarisSandboxClient(
        base_url=POLARIS_SANDBOX_API_URL,
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network request must not be sent"),
    )
    with pytest.raises(PolarisSandboxError, match="malformed"):
        client.detail("../escape")


def test_http_errors_never_include_key_or_response_body():
    body = io.BytesIO(b'{"error":"private-connection-metadata"}')

    def opener(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 403, "forbidden", {}, body)

    client = PolarisSandboxClient(
        base_url=POLARIS_SANDBOX_API_URL, api_key="top-secret", opener=opener
    )
    with pytest.raises(PolarisSandboxError) as raised:
        client.detail("sandbox_123")
    rendered = str(raised.value)
    assert "top-secret" not in rendered
    assert "private-connection-metadata" not in rendered
    assert "sandbox_123" not in rendered


def test_client_repr_redacts_the_api_key():
    client = PolarisSandboxClient(base_url=POLARIS_SANDBOX_API_URL, api_key="top-secret")
    assert "top-secret" not in repr(client)
    assert "<redacted>" in repr(client)


def test_client_refuses_any_host_other_than_the_documented_sandbox_api():
    with pytest.raises(PolarisSandboxError, match="documented API host"):
        PolarisSandboxClient(base_url="https://polaris.example", api_key="secret")


def test_client_reads_a_restricted_env_without_exporting_the_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("POLARIS_API_KEY=top-secret\n", encoding="utf-8")
    env_file.chmod(0o600)
    client = PolarisSandboxClient.from_env_file(env_file)
    assert client.base_url == POLARIS_SANDBOX_API_URL
    assert client.api_key == "top-secret"
    assert os.environ.get("POLARIS_API_KEY") != "top-secret"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_client_rejects_an_env_file_readable_by_other_users(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("POLARIS_API_KEY=top-secret\n", encoding="utf-8")
    env_file.chmod(0o644)
    with pytest.raises(PolarisSandboxError, match="group or others"):
        PolarisSandboxClient.from_env_file(env_file)
