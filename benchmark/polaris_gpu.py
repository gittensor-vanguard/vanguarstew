"""Approval-bound Polaris managed GPU sandbox lifecycle for a public integrity pilot.

Polaris documents an optional managed Hybrid GPU request on ``POST /api/v2/sandbox`` and a
subsequent fresh-nonce re-attestation endpoint.  This module binds the chosen catalog item, live
rate caps, sandbox spend/runtime guardrails, and SSH public key before any billable create.

It does not claim GPU confidentiality.  It also does not guess the undocumented nested shape of
``gpu_provenance``: schema inspection can establish that a block exists, while a later verifier
must be written against an observed, reviewed receipt contract.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import dataclass

from benchmark.polaris_sandbox import (
    POLARIS_SANDBOX_API_URL,
    POLARIS_SANDBOX_CREATE_PATH,
    POLARIS_SANDBOX_SIZE,
    PolarisSandboxClient,
    PolarisSandboxError,
    normalize_ssh_public_key,
)

POLARIS_GPU_CATALOG_PATH = "/api/v2/compute/gpus"
POLARIS_GPU_BILLING_PATH = "/api/billing/credits"
POLARIS_GPU_STATUS_PATH = "/api/v2/sandbox/{sandbox_id}/gpu"
POLARIS_GPU_REATTEST_PATH = "/api/v2/compute/instances/{sandbox_id}/attest"
POLARIS_GPU_PILOT_PROVIDER = "cloud"
POLARIS_GPU_PILOT_MAX_RUNTIME_MINUTES = 60
POLARIS_GPU_PILOT_MIN_RUNTIME_MINUTES = 5

_GPU_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 .+_-]{0,126}[A-Za-z0-9)]")
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_NAME_RE = re.compile(r"gpu-worker-[1-9][0-9]{0,5}")
_NONCE_RE = re.compile(r"[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class PolarisGpuError(RuntimeError):
    """A managed GPU request, catalog, lifecycle response, or receipt failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded_money(value, *, label: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolarisGpuError(f"{label} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < minimum or normalized > 10_000:
        raise PolarisGpuError(f"{label} is outside the accepted bounds")
    if round(normalized, 4) != normalized:
        raise PolarisGpuError(f"{label} must use at most four decimal places")
    return normalized


def _validate_id(value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise PolarisGpuError("sandbox id is malformed")
    return value


@dataclass(frozen=True)
class ManagedGpuSandboxPlan:
    """Network-free plan for one auto-stopped TDX sandbox with a managed spot GPU."""

    name: str
    ssh_public_key: str
    gpu_type: str
    max_gpu_hourly_usd: float
    max_pairing_premium_hourly_usd: float
    max_spend_usd: float = 1.0
    max_runtime_minutes: int = 30
    provider: str = POLARIS_GPU_PILOT_PROVIDER
    use_spot: bool = True

    def __post_init__(self):
        if not isinstance(self.name, str) or not _NAME_RE.fullmatch(self.name):
            raise PolarisGpuError("sandbox name must use the neutral gpu-worker-N format")
        try:
            normalized_key = normalize_ssh_public_key(self.ssh_public_key)
        except PolarisSandboxError as exc:
            raise PolarisGpuError("a canonical Ed25519 SSH public key is required") from exc
        if not isinstance(self.gpu_type, str) or not _GPU_NAME_RE.fullmatch(self.gpu_type):
            raise PolarisGpuError("gpu_type is malformed")
        if self.provider != POLARIS_GPU_PILOT_PROVIDER:
            raise PolarisGpuError("the prototype requires the documented cloud provider route")
        if self.use_spot is not True:
            raise PolarisGpuError("the prototype requires bounded spot capacity")
        if (
            isinstance(self.max_runtime_minutes, bool)
            or not isinstance(self.max_runtime_minutes, int)
            or not POLARIS_GPU_PILOT_MIN_RUNTIME_MINUTES
            <= self.max_runtime_minutes
            <= POLARIS_GPU_PILOT_MAX_RUNTIME_MINUTES
        ):
            raise PolarisGpuError("max_runtime_minutes is outside the pilot bounds")
        object.__setattr__(self, "ssh_public_key", normalized_key)
        object.__setattr__(
            self,
            "max_gpu_hourly_usd",
            _bounded_money(self.max_gpu_hourly_usd, label="max_gpu_hourly_usd", minimum=0.01),
        )
        object.__setattr__(
            self,
            "max_pairing_premium_hourly_usd",
            _bounded_money(
                self.max_pairing_premium_hourly_usd,
                label="max_pairing_premium_hourly_usd",
            ),
        )
        spend = _bounded_money(self.max_spend_usd, label="max_spend_usd", minimum=1.0)
        if round(spend, 2) != spend:
            raise PolarisGpuError("max_spend_usd must use at most two decimal places")
        object.__setattr__(self, "max_spend_usd", spend)
        if self.expected_rate_bound_usd() > self.max_spend_usd:
            raise PolarisGpuError("runtime and hourly caps exceed the sandbox spend guardrail")

    def expected_rate_bound_usd(self) -> float:
        hourly = self.max_gpu_hourly_usd + self.max_pairing_premium_hourly_usd
        return round(hourly * self.max_runtime_minutes / 60.0, 6)

    def request_body(self) -> dict:
        return {
            "name": self.name,
            "size": POLARIS_SANDBOX_SIZE,
            "ssh_public_key": self.ssh_public_key,
            "gpu": {
                "gpu_type": self.gpu_type,
                "provider": self.provider,
                "use_spot": self.use_spot,
            },
            "load_with": {"email": False, "agents": []},
            "primitives": {"email_address": False, "bittensor_intel": False},
            "attested_secrets": False,
            "max_spend_usd": self.max_spend_usd,
            "max_runtime_minutes": self.max_runtime_minutes,
            "auto_stop": True,
        }

    def approval_body(self) -> dict:
        return {
            "request": self.request_body(),
            "catalog_guard": {
                "max_gpu_hourly_usd": self.max_gpu_hourly_usd,
                "max_pairing_premium_hourly_usd": self.max_pairing_premium_hourly_usd,
                "expected_runtime_rate_bound_usd": self.expected_rate_bound_usd(),
                "available_required": True,
            },
            "lifecycle": {
                "billing_preflight": True,
                "poll_owner_detail": True,
                "inspect_gpu_status": True,
                "stop_on_success_or_failure": True,
                "recover_by_name_after_uncertain_create": True,
                "create_retries": 0,
            },
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.approval_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        return {
            "network_request_made": False,
            "method": "POST",
            "endpoint": POLARIS_SANDBOX_API_URL + POLARIS_SANDBOX_CREATE_PATH,
            **self.approval_body(),
            "request_sha256": self.request_sha256(),
            "claim_boundary": {
                "execution_integrity_target": True,
                "workload_confidentiality": False,
                "gpu_provenance_not_yet_observed": True,
            },
        }

    def validate_catalog(self, payload) -> dict:
        """Fail unless the selected live catalog item is available and below both rate caps."""
        if not isinstance(payload, dict) or not isinstance(payload.get("gpus"), list):
            raise PolarisGpuError("Polaris GPU catalog is malformed")
        matches = [
            item
            for item in payload["gpus"]
            if isinstance(item, dict)
            and item.get("name") == self.gpu_type
            and item.get("provider") == self.provider
        ]
        if len(matches) != 1:
            raise PolarisGpuError("selected GPU is not unique in the live catalog")
        selected = matches[0]
        spot_price = selected.get("spot_price")
        sandbox = payload.get("sandbox")
        premium = sandbox.get("gpu_pairing_premium_hourly") if isinstance(sandbox, dict) else None
        if selected.get("available") is not True:
            raise PolarisGpuError("selected GPU is unavailable")
        if (
            isinstance(spot_price, bool)
            or not isinstance(spot_price, (int, float))
            or float(spot_price) > self.max_gpu_hourly_usd
        ):
            raise PolarisGpuError("live GPU spot price exceeds the approved cap")
        if (
            isinstance(premium, bool)
            or not isinstance(premium, (int, float))
            or float(premium) > self.max_pairing_premium_hourly_usd
        ):
            raise PolarisGpuError("live GPU pairing premium exceeds the approved cap")
        return {
            "available": True,
            "gpu_hourly_usd": float(spot_price),
            "pairing_premium_hourly_usd": float(premium),
        }

    def validate_billing(self, payload) -> dict:
        """Require the provider's explicit sandbox-creation eligibility before catalog/create."""
        if not isinstance(payload, dict):
            raise PolarisGpuError("Polaris billing preflight is malformed")
        if payload.get("account_status") != "active" or payload.get("can_create_sandbox") is not True:
            raise PolarisGpuError("Polaris billing preflight does not allow sandbox creation")
        return {"account_active": True, "can_create_sandbox": True}


@dataclass(frozen=True)
class GpuReattestationPlan:
    """Exact fresh-nonce re-attestation request for one already-approved sandbox."""

    sandbox_id: str
    nonce: str

    def __post_init__(self):
        object.__setattr__(self, "sandbox_id", _validate_id(self.sandbox_id))
        if not isinstance(self.nonce, str) or not _NONCE_RE.fullmatch(self.nonce):
            raise PolarisGpuError("nonce must be 32 random bytes encoded as lowercase hex")

    def request_body(self) -> dict:
        return {"nonce": self.nonce}

    def approval_body(self) -> dict:
        return {
            "sandbox_id_sha256": hashlib.sha256(self.sandbox_id.encode("utf-8")).hexdigest(),
            "nonce": self.nonce,
            "method": "POST",
            "path_template": POLARIS_GPU_REATTEST_PATH,
            "request": self.request_body(),
            "retries": 0,
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.approval_body()).encode("utf-8")).hexdigest()


class PolarisGpuClient(PolarisSandboxClient):
    """Documented managed-GPU create, status, and fresh re-attestation operations."""

    def catalog(self) -> dict:
        return self._request_json("GET", POLARIS_GPU_CATALOG_PATH)

    def billing_preflight(self) -> dict:
        return self._request_json("GET", POLARIS_GPU_BILLING_PATH)

    def sandboxes(self) -> dict:
        """List owner-scoped sandboxes for recovery by the plan's unique neutral name."""
        return self._request_json("GET", POLARIS_SANDBOX_CREATE_PATH)

    def create_managed_approved(
        self,
        plan: ManagedGpuSandboxPlan,
        *,
        approved_request_sha256: str,
    ) -> dict:
        if not isinstance(plan, ManagedGpuSandboxPlan):
            raise PolarisGpuError("an exact ManagedGpuSandboxPlan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise PolarisGpuError("approved request digest does not match the managed GPU plan")
        plan.validate_billing(self.billing_preflight())
        plan.validate_catalog(self.catalog())
        payload = self._request_json("POST", POLARIS_SANDBOX_CREATE_PATH, plan.request_body())
        if not isinstance(payload.get("id"), str) or not _ID_RE.fullmatch(payload["id"]):
            raise PolarisGpuError("managed GPU create response is missing a valid sandbox id")
        return payload

    def gpu_status(self, sandbox_id: str) -> dict:
        validated = _validate_id(sandbox_id)
        return self._request_json(
            "GET", POLARIS_GPU_STATUS_PATH.format(sandbox_id=validated)
        )

    def reattest_approved(
        self,
        plan: GpuReattestationPlan,
        *,
        approved_request_sha256: str,
    ) -> dict:
        if not isinstance(plan, GpuReattestationPlan):
            raise PolarisGpuError("an exact GpuReattestationPlan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise PolarisGpuError("approved request digest does not match the re-attestation plan")
        return self._request_json(
            "POST",
            POLARIS_GPU_REATTEST_PATH.format(sandbox_id=plan.sandbox_id),
            plan.request_body(),
        )


def inspect_gpu_provenance_schema(receipt) -> dict:
    """Return only structural paths and types; never infer proof semantics from unknown fields."""
    if not isinstance(receipt, dict):
        return {
            "gpu_provenance_present": False,
            "schema_paths": [],
            "verification_supported": False,
        }
    provenance = receipt.get("gpu_provenance")
    if not isinstance(provenance, dict):
        tee = receipt.get("tee_attestation")
        provenance = tee.get("gpu_provenance") if isinstance(tee, dict) else None
    if not isinstance(provenance, dict):
        return {
            "gpu_provenance_present": False,
            "schema_paths": [],
            "verification_supported": False,
        }

    paths: list[dict] = []

    def visit(value, path: str) -> None:
        if isinstance(value, dict):
            for key in sorted(value):
                child = f"{path}.{key}" if path else str(key)
                visit(value[key], child)
        elif isinstance(value, list):
            paths.append({"path": path, "type": "list", "length": len(value)})
        else:
            paths.append({"path": path, "type": type(value).__name__})

    visit(provenance, "gpu_provenance")
    return {
        "gpu_provenance_present": True,
        "schema_paths": paths,
        "verification_supported": False,
    }
