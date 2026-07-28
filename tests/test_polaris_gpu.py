"""Approval, pricing, lifecycle, and schema tests for the managed Polaris GPU pilot."""

import base64
import json
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.polaris_gpu import (  # noqa: E402
    GpuReattestationPlan,
    ManagedGpuSandboxPlan,
    PolarisGpuClient,
    PolarisGpuError,
    inspect_gpu_provenance_schema,
)
from scripts.plan_managed_gpu_sandbox import build_plan  # noqa: E402


def _ssh_key(comment="operator@example.invalid"):
    key_type = b"ssh-ed25519"
    key_bytes = bytes(range(32))
    wire = (
        struct.pack(">I", len(key_type))
        + key_type
        + struct.pack(">I", len(key_bytes))
        + key_bytes
    )
    return f"ssh-ed25519 {base64.b64encode(wire).decode()} {comment}"


def _plan(**overrides):
    values = {
        "name": "gpu-worker-1",
        "ssh_public_key": _ssh_key(),
        "gpu_type": "RTX PRO 6000 96GB",
        "max_gpu_hourly_usd": 1.32,
        "max_pairing_premium_hourly_usd": 0.15,
        "max_spend_usd": 1.0,
        "max_runtime_minutes": 30,
    }
    values.update(overrides)
    return ManagedGpuSandboxPlan(**values)


def _catalog(**overrides):
    gpu = {
        "name": "RTX PRO 6000 96GB",
        "provider": "cloud",
        "available": True,
        "spot_price": 1.32,
    }
    gpu.update(overrides)
    return {"gpus": [gpu], "sandbox": {"gpu_pairing_premium_hourly": 0.15}}


def _billing(**overrides):
    value = {"account_status": "active", "can_create_sandbox": True}
    value.update(overrides)
    return value


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode()


def test_plan_binds_documented_managed_gpu_request_and_catalog_guards():
    plan = _plan()
    assert plan.request_body() == {
        "name": "gpu-worker-1",
        "size": "Sealed CPU Small",
        "ssh_public_key": " ".join(_ssh_key().split()[:2]),
        "gpu": {
            "gpu_type": "RTX PRO 6000 96GB",
            "provider": "cloud",
            "use_spot": True,
        },
        "load_with": {"email": False, "agents": []},
        "primitives": {"email_address": False, "bittensor_intel": False},
        "attested_secrets": False,
        "max_spend_usd": 1.0,
        "max_runtime_minutes": 30,
        "auto_stop": True,
    }
    assert plan.expected_rate_bound_usd() == 0.735
    summary = plan.approval_summary()
    assert summary["network_request_made"] is False
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["lifecycle"]["create_retries"] == 0
    assert summary["claim_boundary"]["workload_confidentiality"] is False
    assert "operator@example.invalid" not in json.dumps(summary)


def test_cli_reads_only_the_public_key_and_strips_comment(tmp_path):
    key = tmp_path / "id_ed25519.pub"
    key.write_text(_ssh_key("identifying-comment") + "\n", encoding="utf-8")
    plan = build_plan(
        [
            "--ssh-public-key-file",
            str(key),
            "--gpu-type",
            "RTX PRO 6000 96GB",
            "--max-gpu-hourly-usd",
            "1.32",
            "--max-pairing-premium-hourly-usd",
            "0.15",
        ]
    )
    assert "identifying-comment" not in plan.ssh_public_key


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "purpose-name"},
        {"gpu_type": "bad/type"},
        {"provider": "community"},
        {"use_spot": False},
        {"max_runtime_minutes": 4},
        {"max_runtime_minutes": 61},
        {"max_spend_usd": 0.99},
        {"max_gpu_hourly_usd": float("inf")},
        {"max_runtime_minutes": 60, "max_gpu_hourly_usd": 1.0, "max_spend_usd": 1.0},
    ],
)
def test_plan_rejects_unbounded_or_nonprototype_values(changes):
    with pytest.raises(PolarisGpuError):
        _plan(**changes)


def test_live_catalog_must_match_availability_and_rate_caps():
    assert _plan().validate_catalog(_catalog()) == {
        "available": True,
        "gpu_hourly_usd": 1.32,
        "pairing_premium_hourly_usd": 0.15,
    }
    for payload in (
        _catalog(available=False),
        _catalog(spot_price=1.33),
        {"gpus": [_catalog()["gpus"][0], _catalog()["gpus"][0]], "sandbox": {}},
        {"gpus": _catalog()["gpus"], "sandbox": {"gpu_pairing_premium_hourly": 0.16}},
        {"unexpected": []},
    ):
        with pytest.raises(PolarisGpuError):
            _plan().validate_catalog(payload)


def test_billing_preflight_requires_active_creation_eligibility():
    assert _plan().validate_billing(_billing()) == {
        "account_active": True,
        "can_create_sandbox": True,
    }
    for payload in (
        _billing(account_status="suspended"),
        _billing(can_create_sandbox=False),
        [],
    ):
        with pytest.raises(PolarisGpuError):
            _plan().validate_billing(payload)


def test_create_checks_catalog_then_posts_only_the_approved_request():
    seen = []

    def opener(request, timeout):
        seen.append((request.get_method(), request.full_url, request.data))
        if request.get_method() == "GET":
            if request.full_url.endswith("/api/billing/credits"):
                return _Response(_billing())
            return _Response(_catalog())
        return _Response({"id": "sandbox_123", "status": "provisioning"})

    plan = _plan()
    client = PolarisGpuClient(
        base_url="https://api.polaris.computer", api_key="secret", opener=opener
    )
    result = client.create_managed_approved(
        plan,
        approved_request_sha256=plan.request_sha256(),
    )
    assert result["id"] == "sandbox_123"
    assert seen == [
        ("GET", "https://api.polaris.computer/api/billing/credits", None),
        ("GET", "https://api.polaris.computer/api/v2/compute/gpus", None),
        (
            "POST",
            "https://api.polaris.computer/api/v2/sandbox",
            json.dumps(plan.request_body(), sort_keys=True, separators=(",", ":")).encode(),
        ),
    ]


def test_owner_sandbox_list_is_available_for_uncertain_create_recovery():
    seen = []

    def opener(request, timeout):
        seen.append((request.get_method(), request.full_url))
        return _Response({"sandboxes": []})

    client = PolarisGpuClient(
        base_url="https://api.polaris.computer", api_key="secret", opener=opener
    )
    assert client.sandboxes() == {"sandboxes": []}
    assert seen == [("GET", "https://api.polaris.computer/api/v2/sandbox")]


def test_create_rejects_changed_approval_before_catalog_or_create():
    client = PolarisGpuClient(
        base_url="https://api.polaris.computer",
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network request must not be sent"),
    )
    with pytest.raises(PolarisGpuError, match="approved"):
        client.create_managed_approved(_plan(), approved_request_sha256="00" * 32)


def test_gpu_status_and_reattest_use_only_documented_routes():
    seen = []

    def opener(request, timeout):
        seen.append((request.get_method(), request.full_url, request.data))
        return _Response({"status": "ok"})

    client = PolarisGpuClient(
        base_url="https://api.polaris.computer", api_key="secret", opener=opener
    )
    assert client.gpu_status("sandbox_123")["status"] == "ok"
    plan = GpuReattestationPlan(sandbox_id="sandbox_123", nonce="ab" * 32)
    client.reattest_approved(plan, approved_request_sha256=plan.request_sha256())
    assert seen == [
        ("GET", "https://api.polaris.computer/api/v2/sandbox/sandbox_123/gpu", None),
        (
            "POST",
            "https://api.polaris.computer/api/v2/compute/instances/sandbox_123/attest",
            b'{"nonce":"' + b"ab" * 32 + b'"}',
        ),
    ]


def test_reattest_rejects_bad_nonce_approval_and_id_before_network():
    with pytest.raises(PolarisGpuError):
        GpuReattestationPlan(sandbox_id="../escape", nonce="ab" * 32)
    with pytest.raises(PolarisGpuError):
        GpuReattestationPlan(sandbox_id="sandbox_1", nonce="short")
    plan = GpuReattestationPlan(sandbox_id="sandbox_1", nonce="ab" * 32)
    client = PolarisGpuClient(
        base_url="https://api.polaris.computer",
        api_key="secret",
        opener=lambda *args, **kwargs: pytest.fail("network request must not be sent"),
    )
    with pytest.raises(PolarisGpuError, match="approved"):
        client.reattest_approved(plan, approved_request_sha256="00" * 32)


def test_provenance_inspector_reports_only_schema_and_never_claims_verification():
    receipt = {
        "gpu_provenance": {
            "model": {"digest": "secret-value"},
            "egress": ["secret-host"],
            "exclusive": True,
        }
    }
    result = inspect_gpu_provenance_schema(receipt)
    assert result == {
        "gpu_provenance_present": True,
        "schema_paths": [
            {"path": "gpu_provenance.egress", "type": "list", "length": 1},
            {"path": "gpu_provenance.exclusive", "type": "bool"},
            {"path": "gpu_provenance.model.digest", "type": "str"},
        ],
        "verification_supported": False,
    }
    assert "secret-value" not in json.dumps(result)
    assert "secret-host" not in json.dumps(result)
    assert inspect_gpu_provenance_schema({})["gpu_provenance_present"] is False
