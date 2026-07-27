"""Fail-closed adapter for a bare persistent Polaris TDX sandbox.

This module is intentionally separate from :mod:`benchmark.polaris`.  ``/v1/attest`` produces a
one-shot proof; ``/api/v2/sandbox`` creates a persistent SSH-accessible TDX machine.  The private
workload path represented here cannot request a public container image, preload agents, provision
an inbox, or enable attested-secret injection.

Creating a sandbox changes external state and can spend money.  Callers must first render the exact
offline plan and then pass its SHA-256 back to :meth:`PolarisSandboxClient.create_approved`.  This
does not replace operator approval, but it prevents an approved payload from changing silently
between review and execution.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import math
import os
import re
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

POLARIS_SANDBOX_API_URL = "https://api.polaris.computer"
POLARIS_SANDBOX_CREATE_PATH = "/api/v2/sandbox"
POLARIS_SANDBOX_SIZE = "Sealed CPU Small"
POLARIS_SANDBOX_MIN_SPEND_USD = 1.0
POLARIS_SANDBOX_MAX_SPEND_USD = 10_000.0
POLARIS_SANDBOX_MIN_RUNTIME_MINUTES = 5
POLARIS_SANDBOX_MAX_RUNTIME_MINUTES = 7 * 24 * 60

_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_NAME_RE = re.compile(r"sealed-worker-[1-9][0-9]{0,5}")
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class PolarisSandboxError(RuntimeError):
    """A sandbox plan, request, or response failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_ssh_string(value: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(value):
        raise PolarisSandboxError("SSH public key is truncated")
    length = struct.unpack(">I", value[offset : offset + 4])[0]
    start = offset + 4
    end = start + length
    if end > len(value):
        raise PolarisSandboxError("SSH public key is truncated")
    return value[start:end], end


def normalize_ssh_public_key(value: str) -> str:
    """Return a comment-free Ed25519 public key after validating its OpenSSH wire form."""
    if not isinstance(value, str):
        raise PolarisSandboxError("SSH public key must be text")
    parts = value.strip().split()
    if len(parts) < 2 or parts[0] != "ssh-ed25519":
        raise PolarisSandboxError("an ssh-ed25519 public key is required")
    try:
        decoded = base64.b64decode(parts[1].encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise PolarisSandboxError("SSH public key is not valid base64") from exc
    key_type, offset = _read_ssh_string(decoded, 0)
    key_bytes, offset = _read_ssh_string(decoded, offset)
    if key_type != b"ssh-ed25519" or len(key_bytes) != 32 or offset != len(decoded):
        raise PolarisSandboxError("SSH public key is not a canonical Ed25519 key")
    return f"ssh-ed25519 {parts[1]}"


def _validate_name(value: str) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise PolarisSandboxError("sandbox name must use the neutral sealed-worker-N format")
    return value


def _validate_spend(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolarisSandboxError("max_spend_usd must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise PolarisSandboxError("max_spend_usd must be finite")
    if not POLARIS_SANDBOX_MIN_SPEND_USD <= normalized <= POLARIS_SANDBOX_MAX_SPEND_USD:
        raise PolarisSandboxError("max_spend_usd is outside Polaris's documented bounds")
    if round(normalized, 2) != normalized:
        raise PolarisSandboxError("max_spend_usd must use at most two decimal places")
    return normalized


def _validate_runtime(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolarisSandboxError("max_runtime_minutes must be an integer")
    if not POLARIS_SANDBOX_MIN_RUNTIME_MINUTES <= value <= POLARIS_SANDBOX_MAX_RUNTIME_MINUTES:
        raise PolarisSandboxError("max_runtime_minutes is outside Polaris's documented bounds")
    return value


@dataclass(frozen=True)
class PolarisSandboxPlan:
    """Exact, network-free plan for one neutral bare TDX sandbox."""

    name: str
    ssh_public_key: str
    max_spend_usd: float
    max_runtime_minutes: int

    def __post_init__(self):
        object.__setattr__(self, "name", _validate_name(self.name))
        object.__setattr__(self, "ssh_public_key", normalize_ssh_public_key(self.ssh_public_key))
        object.__setattr__(self, "max_spend_usd", _validate_spend(self.max_spend_usd))
        object.__setattr__(self, "max_runtime_minutes", _validate_runtime(self.max_runtime_minutes))

    def request_body(self) -> dict:
        """Return the only sandbox request shape accepted by this integration."""
        return {
            "name": self.name,
            "size": POLARIS_SANDBOX_SIZE,
            "ssh_public_key": self.ssh_public_key,
            "load_with": {"email": False, "agents": []},
            "primitives": {"email_address": False, "bittensor_intel": False},
            "attested_secrets": False,
            "max_spend_usd": self.max_spend_usd,
            "max_runtime_minutes": self.max_runtime_minutes,
            "auto_stop": True,
        }

    def request_sha256(self) -> str:
        """Bind approval to the exact canonical request bytes."""
        return hashlib.sha256(_canonical_json(self.request_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        """Return a local approval plan with no API key or returned connection metadata."""
        return {
            "network_request_made": False,
            "method": "POST",
            "endpoint": POLARIS_SANDBOX_API_URL + POLARIS_SANDBOX_CREATE_PATH,
            "request": self.request_body(),
            "request_sha256": self.request_sha256(),
            "privacy": {
                "container_image_omitted": True,
                "agent_preload_disabled": True,
                "inbox_disabled": True,
                "attested_secrets_disabled": True,
                "ssh_key_comment_removed": True,
            },
        }


class PolarisSandboxClient:
    """Minimal live client for approved create, private detail, and approved stop operations."""

    def __init__(self, *, base_url: str, api_key: str, timeout: float = 240.0, opener=None):
        if not isinstance(base_url, str) or base_url.rstrip("/") != POLARIS_SANDBOX_API_URL:
            raise PolarisSandboxError("Polaris sandbox base URL must be the documented API host")
        if not isinstance(api_key, str) or not api_key:
            raise PolarisSandboxError("Polaris API key must be non-empty")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise PolarisSandboxError("Polaris sandbox timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"timeout={self.timeout!r}, api_key=<redacted>)"
        )

    @classmethod
    def from_env_file(
        cls,
        path,
        *,
        base_url: str = POLARIS_SANDBOX_API_URL,
        api_key_name: str = "POLARIS_API_KEY",
        timeout: float = 240.0,
        opener=None,
    ) -> "PolarisSandboxClient":
        """Read only the API key from a permission-restricted dotenv file."""
        env_path = Path(path)
        try:
            file_mode = env_path.stat().st_mode
            text = env_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolarisSandboxError("cannot read Polaris env file") from exc
        if os.name != "nt" and file_mode & 0o077:
            raise PolarisSandboxError("Polaris env file must not be accessible by group or others")

        values = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            if key in values:
                raise PolarisSandboxError("Polaris env file contains a duplicate variable")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
        api_key = values.get(api_key_name, "")
        if not api_key and api_key_name == "POLARIS_API_KEY":
            api_key = values.get("POLARIS_KEY", "")
        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
            opener=opener,
        )

    def _request_json(self, method: str, path: str, body: dict | None = None) -> dict:
        encoded = None if body is None else _canonical_json(body).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "vanguarstew-polaris-sandbox/1",
        }
        if encoded is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            data=encoded,
            headers=headers,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            raise PolarisSandboxError(f"Polaris sandbox request failed (HTTP {exc.code})") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise PolarisSandboxError(
                f"Polaris sandbox request failed ({type(exc).__name__})"
            ) from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise PolarisSandboxError("Polaris sandbox response exceeded the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PolarisSandboxError("Polaris sandbox returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PolarisSandboxError("Polaris sandbox response is not an object")
        return payload

    def create_approved(self, plan: PolarisSandboxPlan, *, approved_request_sha256: str) -> dict:
        """Create a sandbox only when the approval digest matches the exact request body."""
        if not isinstance(plan, PolarisSandboxPlan):
            raise PolarisSandboxError("an exact PolarisSandboxPlan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise PolarisSandboxError("approved request digest does not match the sandbox plan")
        payload = self._request_json("POST", POLARIS_SANDBOX_CREATE_PATH, plan.request_body())
        if not isinstance(payload.get("id"), str) or not payload["id"]:
            raise PolarisSandboxError("Polaris sandbox create response is missing an id")
        return payload

    def detail(self, sandbox_id: str) -> dict:
        """Read owner-scoped sandbox detail without rendering it to logs."""
        if not isinstance(sandbox_id, str) or not _ID_RE.fullmatch(sandbox_id):
            raise PolarisSandboxError("sandbox id is malformed")
        return self._request_json("GET", f"{POLARIS_SANDBOX_CREATE_PATH}/{sandbox_id}")

    def stop_approved(self, sandbox_id: str, *, approved_sandbox_id: str) -> dict:
        """Stop exactly the sandbox id approved by the operator."""
        if not isinstance(sandbox_id, str) or not _ID_RE.fullmatch(sandbox_id):
            raise PolarisSandboxError("sandbox id is malformed")
        if not isinstance(approved_sandbox_id, str) or not hmac.compare_digest(
            sandbox_id, approved_sandbox_id
        ):
            raise PolarisSandboxError("approved sandbox id does not match the stop target")
        return self._request_json("DELETE", f"{POLARIS_SANDBOX_CREATE_PATH}/{sandbox_id}")
