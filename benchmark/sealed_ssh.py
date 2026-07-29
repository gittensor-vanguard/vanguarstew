"""Fail-closed staging for an operator-approved payload over a pinned SSH connection.

This module never discovers or trusts a host key.  The caller must supply a non-empty mode-0600
``known_hosts`` file and accept the trust decision used to create it.  Polaris's public boot receipt
binds the customer SSH key, not the SSH server host key or a later uploaded workload, so successful
staging must not be represented as end-to-end workload attestation.

Only a content-addressed archive is staged.  Extraction and execution are deliberately separate
operations requiring their own reviewed protocol and approval.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.sealed_aggregate import SEALED_AGGREGATE_CONTRACT

SEALED_SSH_PROTOCOL_VERSION = 1
SEALED_SSH_MAX_BUNDLE_BYTES = 64 * 1024 * 1024

_CHALLENGE_RE = re.compile(r"[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,253}")
_USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,31}")


class SealedSSHError(RuntimeError):
    """A sealed SSH connection, approval, or staging operation failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _restricted_regular_file(path, *, label: str, max_bytes: int | None = None) -> tuple[Path, int]:
    candidate = Path(path)
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise SealedSSHError(f"cannot read {label}") from exc
    if not stat.S_ISREG(info.st_mode) or candidate.is_symlink():
        raise SealedSSHError(f"{label} must be a regular file")
    if os.name != "nt" and info.st_mode & 0o077:
        raise SealedSSHError(f"{label} must not be accessible by group or others")
    if info.st_size <= 0:
        raise SealedSSHError(f"{label} must be non-empty")
    if max_bytes is not None and info.st_size > max_bytes:
        raise SealedSSHError(f"{label} exceeds the size limit")
    return candidate, info.st_size


def _read_bundle(path: Path) -> bytes:
    candidate, expected_size = _restricted_regular_file(
        path,
        label="deployment bundle",
        max_bytes=SEALED_SSH_MAX_BUNDLE_BYTES,
    )
    try:
        value = candidate.read_bytes()
    except OSError as exc:
        raise SealedSSHError("cannot read deployment bundle") from exc
    if len(value) != expected_size:
        raise SealedSSHError("deployment bundle changed while reading")
    return value


@dataclass(frozen=True)
class SealedSSHConnection:
    """Owner-scoped SSH coordinates whose representation is always redacted."""

    host: str
    port: int
    user: str
    identity_file: Path
    known_hosts_file: Path

    def __post_init__(self):
        if not isinstance(self.host, str) or not _HOST_RE.fullmatch(self.host):
            raise SealedSSHError("SSH host is malformed")
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise SealedSSHError("SSH port is malformed")
        if not isinstance(self.user, str) or not _USER_RE.fullmatch(self.user):
            raise SealedSSHError("SSH user is malformed")
        try:
            identity_path = Path(self.identity_file)
            known_hosts_path = Path(self.known_hosts_file)
        except TypeError as exc:
            raise SealedSSHError("SSH file path is malformed") from exc
        identity, _ = _restricted_regular_file(identity_path, label="SSH identity file")
        known_hosts, _ = _restricted_regular_file(
            known_hosts_path,
            label="SSH known-hosts file",
        )
        object.__setattr__(self, "identity_file", identity)
        object.__setattr__(self, "known_hosts_file", known_hosts)

    @classmethod
    def from_owner_detail(
        cls,
        detail,
        *,
        identity_file,
        known_hosts_file,
    ) -> "SealedSSHConnection":
        """Read only the documented SSH fields from an owner-detail response."""
        if not isinstance(detail, dict):
            raise SealedSSHError("sandbox owner detail must be an object")
        return cls(
            host=detail.get("ssh_host"),
            port=detail.get("ssh_port"),
            user=detail.get("ssh_user"),
            identity_file=identity_file,
            known_hosts_file=known_hosts_file,
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}(<redacted>)"

    def ssh_argv(self, remote_command: str) -> list[str]:
        if not isinstance(remote_command, str) or not remote_command:
            raise SealedSSHError("remote command must be non-empty")
        return [
            "ssh",
            "-T",
            "-i",
            str(self.identity_file),
            "-p",
            str(self.port),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.known_hosts_file}",
            "-o",
            "ForwardAgent=no",
            "-o",
            "ClearAllForwardings=yes",
            "-o",
            "PermitLocalCommand=no",
            "-o",
            "RequestTTY=no",
            f"{self.user}@{self.host}",
            remote_command,
        ]


@dataclass(frozen=True)
class SealedSSHDeploymentPlan:
    """Network-free plan for staging one bounded, content-addressed bundle."""

    bundle_path: Path
    challenge: str
    bundle_sha256: str = field(init=False)
    bundle_bytes: int = field(init=False)

    def __post_init__(self):
        if not isinstance(self.challenge, str) or not _CHALLENGE_RE.fullmatch(self.challenge):
            raise SealedSSHError("challenge must be 32 random bytes encoded as lowercase hex")
        bundle = _read_bundle(Path(self.bundle_path))
        object.__setattr__(self, "bundle_path", Path(self.bundle_path))
        object.__setattr__(self, "bundle_sha256", hashlib.sha256(bundle).hexdigest())
        object.__setattr__(self, "bundle_bytes", len(bundle))

    @property
    def remote_bundle(self) -> str:
        return f".sealed-worker/payload-{self.bundle_sha256}.tar"

    def request_body(self) -> dict:
        return {
            "version": SEALED_SSH_PROTOCOL_VERSION,
            "bundle_sha256": self.bundle_sha256,
            "bundle_bytes": self.bundle_bytes,
            "remote_bundle": self.remote_bundle,
            "result_contract": SEALED_AGGREGATE_CONTRACT,
            "challenge": self.challenge,
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.request_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        """Return a connection-free plan suitable for local operator review."""
        return {
            "network_request_made": False,
            "operation": "stage-content-addressed-bundle",
            "request": self.request_body(),
            "request_sha256": self.request_sha256(),
            "privacy": {
                "connection_metadata_omitted": True,
                "local_path_omitted": True,
                "strict_host_key_checking_required": True,
                "agent_forwarding_disabled": True,
                "remote_execution_excluded": True,
            },
        }


class SealedSSHTransport:
    """Stage an exact approved bundle with no retry and no remote execution."""

    def __init__(self, *, timeout: float = 120.0, runner=None):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
            raise SealedSSHError("SSH timeout must be positive")
        self.timeout = float(timeout)
        self._runner = runner or subprocess.run

    def stage_approved(
        self,
        connection: SealedSSHConnection,
        plan: SealedSSHDeploymentPlan,
        *,
        approved_request_sha256: str,
    ) -> dict:
        """Upload and hash-check only the exact operator-approved bundle."""
        if not isinstance(connection, SealedSSHConnection):
            raise SealedSSHError("a validated sealed SSH connection is required")
        if not isinstance(plan, SealedSSHDeploymentPlan):
            raise SealedSSHError("an exact sealed SSH deployment plan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise SealedSSHError("approved request digest does not match the staging plan")

        bundle = _read_bundle(plan.bundle_path)
        if not hmac.compare_digest(hashlib.sha256(bundle).hexdigest(), plan.bundle_sha256):
            raise SealedSSHError("deployment bundle changed after approval")
        upload_path = f"{plan.remote_bundle}.upload"
        upload_command = (
            "umask 077; install -d -m 700 .sealed-worker; "
            f"test ! -e {plan.remote_bundle} && test ! -e {upload_path} && cat > {upload_path}"
        )
        verify_command = (
            "set -eu; "
            f"printf '%s  %s\\n' {plan.bundle_sha256} {upload_path} | sha256sum -c - >/dev/null; "
            f"chmod 600 {upload_path}; mv {upload_path} {plan.remote_bundle}"
        )
        for argv, input_bytes in (
            (connection.ssh_argv(upload_command), bundle),
            (connection.ssh_argv(verify_command), None),
        ):
            try:
                result = self._runner(
                    argv,
                    input=input_bytes,
                    capture_output=True,
                    check=False,
                    timeout=self.timeout,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SealedSSHError("sealed SSH staging failed") from exc
            if result.returncode != 0:
                raise SealedSSHError("sealed SSH staging failed")
        return {
            "staged": True,
            "remote_execution_performed": False,
        }
