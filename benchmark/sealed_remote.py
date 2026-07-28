"""Target-bound SSH invocation of the public sealed runtime with aggregate-only output.

The Polaris boot receipt does not bind the SSH server host key, this runtime, the staged payload,
the remote command, or its output.  This protocol therefore provides an exact operator-approval
boundary and output minimization; it is not end-to-end workload attestation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

try:
    import resource
except ImportError:  # pragma: no cover - POSIX-only live surface
    resource = None

from benchmark.sealed_aggregate import SEALED_AGGREGATE_CONTRACT, verify_sealed_aggregate
from benchmark.sealed_execution import SealedExecutionError, SealedExecutionPlan
from benchmark.sealed_runtime import (
    SEALED_RUNTIME_MAX_BYTES,
    SealedRuntimeError,
    inspect_sealed_runtime,
)
from benchmark.sealed_ssh import SealedSSHConnection

SEALED_REMOTE_VERSION = 1
SEALED_REMOTE_CONTROL_TIMEOUT_SECONDS = 120
SEALED_REMOTE_TIMEOUT_MARGIN_SECONDS = 30
SEALED_REMOTE_MAX_STDOUT_BYTES = 4096
SEALED_REMOTE_MAX_OWNER_DETAIL_BYTES = 1024 * 1024

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_HOST_RE = re.compile(r"[A-Za-z0-9.-]{1,253}")
_USER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,31}")


class SealedRemoteError(RuntimeError):
    """A remote plan, target binding, SSH operation, or aggregate failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _read_restricted_file(path: Path, *, label: str, max_bytes: int) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= max_bytes:
            raise SealedRemoteError(f"{label} is not a bounded regular file")
        if os.name != "nt" and info.st_mode & 0o077:
            raise SealedRemoteError(f"{label} must not be accessible by group or others")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise SealedRemoteError(f"{label} changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SealedRemoteError(f"{label} changed while reading")
        return b"".join(chunks)
    except SealedRemoteError:
        raise
    except OSError as exc:
        raise SealedRemoteError(f"cannot read {label}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def load_owner_detail(path) -> dict:
    """Load one permission-restricted owner-detail response without rendering any field value."""
    raw = _read_restricted_file(
        Path(path),
        label="sandbox owner detail",
        max_bytes=SEALED_REMOTE_MAX_OWNER_DETAIL_BYTES,
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SealedRemoteError("sandbox owner detail is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SealedRemoteError("sandbox owner detail must be an object")
    return value


def owner_target_binding(detail, known_hosts_file) -> str:
    """Bind the sandbox id, documented SSH target fields, and exact pinned host-key file."""
    if not isinstance(detail, dict):
        raise SealedRemoteError("sandbox owner detail must be an object")
    sandbox_id = detail.get("id")
    host = detail.get("ssh_host")
    port = detail.get("ssh_port")
    user = detail.get("ssh_user")
    if not isinstance(sandbox_id, str) or not _ID_RE.fullmatch(sandbox_id):
        raise SealedRemoteError("sandbox owner detail id is malformed")
    if not isinstance(host, str) or not _HOST_RE.fullmatch(host):
        raise SealedRemoteError("sandbox owner detail SSH host is malformed")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SealedRemoteError("sandbox owner detail SSH port is malformed")
    if not isinstance(user, str) or not _USER_RE.fullmatch(user):
        raise SealedRemoteError("sandbox owner detail SSH user is malformed")
    known_hosts = _read_restricted_file(
        Path(known_hosts_file),
        label="SSH known-hosts file",
        max_bytes=SEALED_REMOTE_MAX_OWNER_DETAIL_BYTES,
    )
    body = {
        "sandbox_id": sandbox_id,
        "ssh_host": host,
        "ssh_port": port,
        "ssh_user": user,
        "known_hosts_sha256": hashlib.sha256(known_hosts).hexdigest(),
    }
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def _connection_matches_detail(connection: SealedSSHConnection, detail: dict) -> bool:
    try:
        return (
            connection.host == detail.get("ssh_host")
            and connection.port == detail.get("ssh_port")
            and connection.user == detail.get("ssh_user")
        )
    except (AttributeError, TypeError):
        return False


@dataclass(frozen=True)
class SealedRemoteExecutionPlan:
    """Network-free plan for one target-bound, already-staged bundle execution."""

    runtime_path: Path
    bundle_path: Path
    challenge: str
    target_binding_sha256: str
    timeout_seconds: int = 900
    max_output_bytes: int = 8 * 1024 * 1024
    max_memory_bytes: int = 1024 * 1024 * 1024
    runtime_sha256: str = field(init=False)
    runtime_bytes: int = field(init=False)
    runtime_source_revision: str = field(init=False)
    bundle_sha256: str = field(init=False)
    bundle_bytes: int = field(init=False)
    execution_request_sha256: str = field(init=False)

    def __post_init__(self):
        if not isinstance(self.target_binding_sha256, str) or not _SHA256_RE.fullmatch(
            self.target_binding_sha256
        ):
            raise SealedRemoteError("target binding digest is malformed")
        source_root = Path(__file__).resolve().parents[1]
        try:
            runtime_path = Path(self.runtime_path)
            runtime = inspect_sealed_runtime(runtime_path, source_root=source_root)
            execution = SealedExecutionPlan(
                bundle_path=Path(self.bundle_path),
                challenge=self.challenge,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
                max_memory_bytes=self.max_memory_bytes,
            )
        except (TypeError, ValueError, SealedExecutionError, SealedRuntimeError) as exc:
            raise SealedRemoteError("sealed remote execution inputs are invalid") from exc
        object.__setattr__(self, "runtime_path", runtime_path)
        object.__setattr__(self, "bundle_path", execution.bundle_path)
        object.__setattr__(self, "runtime_sha256", runtime.runtime_sha256)
        object.__setattr__(self, "runtime_bytes", runtime.runtime_bytes)
        object.__setattr__(self, "runtime_source_revision", runtime.source_revision)
        object.__setattr__(self, "bundle_sha256", execution.bundle_sha256)
        object.__setattr__(self, "bundle_bytes", execution.bundle_bytes)
        object.__setattr__(self, "execution_request_sha256", execution.request_sha256())

    @property
    def remote_runtime(self) -> str:
        return f".sealed-worker/runtime-{self.runtime_sha256}.pyz"

    @property
    def remote_bundle(self) -> str:
        return f".sealed-worker/payload-{self.bundle_sha256}.tar"

    def request_body(self) -> dict:
        return {
            "version": SEALED_REMOTE_VERSION,
            "target_binding_sha256": self.target_binding_sha256,
            "runtime_sha256": self.runtime_sha256,
            "runtime_bytes": self.runtime_bytes,
            "runtime_source_revision": self.runtime_source_revision,
            "remote_runtime": self.remote_runtime,
            "bundle_sha256": self.bundle_sha256,
            "bundle_bytes": self.bundle_bytes,
            "remote_bundle": self.remote_bundle,
            "challenge": self.challenge,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "execution_request_sha256": self.execution_request_sha256,
            "result_contract": SEALED_AGGREGATE_CONTRACT,
            "cleanup_policy": "remove-exact-runtime-and-bundle-v1",
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.request_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        return {
            "network_request_made": False,
            "operation": "verify-stage-runtime-execute-aggregate-cleanup",
            "request": self.request_body(),
            "request_sha256": self.request_sha256(),
            "preconditions": {
                "payload_already_staged_at_content_address": True,
                "pinned_known_host_required": True,
                "boot_receipt_privacy_gate_already_passed": True,
            },
            "privacy": {
                "connection_metadata_omitted": True,
                "sandbox_id_omitted": True,
                "local_paths_omitted": True,
                "runtime_member_names_omitted": True,
                "stderr_discarded": True,
                "stdout_aggregate_only": True,
                "exact_remote_cleanup_required": True,
            },
            "limitations": {
                "ssh_host_key_is_not_quote_bound": True,
                "runtime_is_not_quote_bound": True,
                "payload_is_not_quote_bound": True,
                "command_is_not_quote_bound": True,
                "output_is_not_quote_bound": True,
                "filesystem_is_not_an_adversarial_sandbox": True,
            },
        }


def _output_limits(max_stdout_bytes: int):
    def apply_limits():
        if resource is None:
            return
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_stdout_bytes, max_stdout_bytes))

    return apply_limits


def _run_ssh_bounded(
    argv,
    *,
    input: bytes | None,
    timeout: float,
    max_stdout_bytes: int,
) -> SimpleNamespace:
    if sys.platform != "linux" or resource is None:
        raise SealedRemoteError("bounded SSH execution requires Linux resource limits")
    with tempfile.TemporaryFile() as stdout_file:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            preexec_fn=_output_limits(max_stdout_bytes),
        )
        try:
            process.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()
            process.wait()
            raise
        stdout_file.seek(0)
        stdout = stdout_file.read(max_stdout_bytes + 1)
    return SimpleNamespace(returncode=process.returncode, stdout=stdout)


class SealedRemoteExecutor:
    """Verify a staged payload, stage the public runtime, execute once, and clean exact paths."""

    def __init__(self, *, runner=None):
        self._runner = runner or _run_ssh_bounded

    def _invoke(
        self,
        connection: SealedSSHConnection,
        command: str,
        *,
        input_bytes: bytes | None,
        timeout: float,
        allow_stdout: bool,
    ) -> bytes:
        try:
            result = self._runner(
                connection.ssh_argv(command),
                input=input_bytes,
                timeout=timeout,
                max_stdout_bytes=SEALED_REMOTE_MAX_STDOUT_BYTES,
            )
        except Exception as exc:
            raise SealedRemoteError("sealed remote SSH operation failed") from exc
        stdout = getattr(result, "stdout", b"")
        if (
            getattr(result, "returncode", None) != 0
            or not isinstance(stdout, bytes)
            or len(stdout) > SEALED_REMOTE_MAX_STDOUT_BYTES
            or (stdout and not allow_stdout)
        ):
            raise SealedRemoteError("sealed remote SSH operation failed")
        return stdout

    def execute_approved(
        self,
        connection: SealedSSHConnection,
        plan: SealedRemoteExecutionPlan,
        *,
        owner_detail: dict,
        approved_request_sha256: str,
    ) -> str:
        if not isinstance(connection, SealedSSHConnection):
            raise SealedRemoteError("a validated sealed SSH connection is required")
        if not isinstance(plan, SealedRemoteExecutionPlan):
            raise SealedRemoteError("an exact sealed remote execution plan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise SealedRemoteError("approved request digest does not match the remote plan")
        target_binding = owner_target_binding(owner_detail, connection.known_hosts_file)
        if not _connection_matches_detail(connection, owner_detail) or not hmac.compare_digest(
            plan.target_binding_sha256, target_binding
        ):
            raise SealedRemoteError("sealed remote target does not match the approved plan")

        source_root = Path(__file__).resolve().parents[1]
        try:
            runtime_info = inspect_sealed_runtime(plan.runtime_path, source_root=source_root)
            runtime = _read_restricted_file(
                plan.runtime_path,
                label="sealed runtime",
                max_bytes=SEALED_RUNTIME_MAX_BYTES,
            )
            execution = SealedExecutionPlan(
                bundle_path=plan.bundle_path,
                challenge=plan.challenge,
                timeout_seconds=plan.timeout_seconds,
                max_output_bytes=plan.max_output_bytes,
                max_memory_bytes=plan.max_memory_bytes,
            )
        except (ValueError, SealedExecutionError, SealedRuntimeError) as exc:
            raise SealedRemoteError("sealed remote inputs changed after approval") from exc
        if (
            not hmac.compare_digest(runtime_info.runtime_sha256, plan.runtime_sha256)
            or len(runtime) != plan.runtime_bytes
            or not hmac.compare_digest(hashlib.sha256(runtime).hexdigest(), plan.runtime_sha256)
            or not hmac.compare_digest(execution.bundle_sha256, plan.bundle_sha256)
            or not hmac.compare_digest(execution.request_sha256(), plan.execution_request_sha256)
        ):
            raise SealedRemoteError("sealed remote inputs changed after approval")

        runtime_upload = f"{plan.remote_runtime}.upload"
        bundle_upload = f"{plan.remote_bundle}.upload"
        verify_bundle = (
            "set -eu; "
            f"test -f {plan.remote_bundle}; "
            f"test ! -L {plan.remote_bundle}; "
            f"test $(stat -c %a {plan.remote_bundle}) = 600; "
            f"test $(stat -c %s {plan.remote_bundle}) = {plan.bundle_bytes}; "
            f"printf '%s  %s\\n' {plan.bundle_sha256} {plan.remote_bundle} | "
            "sha256sum -c - >/dev/null"
        )
        upload_runtime = (
            "set -eu; umask 077; install -d -m 700 .sealed-worker; "
            f"test ! -e {plan.remote_runtime}; test ! -e {runtime_upload}; "
            f"cat > {runtime_upload}"
        )
        verify_runtime = (
            "set -eu; "
            f"test $(stat -c %s {runtime_upload}) = {plan.runtime_bytes}; "
            f"printf '%s  %s\\n' {plan.runtime_sha256} {runtime_upload} | "
            "sha256sum -c - >/dev/null; "
            f"chmod 600 {runtime_upload}; mv {runtime_upload} {plan.remote_runtime}"
        )
        execute = (
            "set -eu; umask 077; exec env -i PATH=/usr/bin:/bin LANG=C.UTF-8 "
            "LC_ALL=C.UTF-8 PYTHONHASHSEED=0 python3 "
            f"{plan.remote_runtime} "
            f"--runtime-sha256 {plan.runtime_sha256} "
            f"--bundle {plan.remote_bundle} "
            f"--challenge {plan.challenge} "
            f"--timeout-seconds {plan.timeout_seconds} "
            f"--max-output-bytes {plan.max_output_bytes} "
            f"--max-memory-bytes {plan.max_memory_bytes} "
            f"--approved-request-sha256 {plan.execution_request_sha256}"
        )
        cleanup = (
            "set -eu; "
            f"rm -f {plan.remote_runtime} {runtime_upload} {plan.remote_bundle} {bundle_upload}; "
            "rmdir .sealed-worker 2>/dev/null || true"
        )

        envelope = None
        operation_error = None
        cleanup_error = None
        try:
            self._invoke(
                connection,
                verify_bundle,
                input_bytes=None,
                timeout=SEALED_REMOTE_CONTROL_TIMEOUT_SECONDS,
                allow_stdout=False,
            )
            self._invoke(
                connection,
                upload_runtime,
                input_bytes=runtime,
                timeout=SEALED_REMOTE_CONTROL_TIMEOUT_SECONDS,
                allow_stdout=False,
            )
            self._invoke(
                connection,
                verify_runtime,
                input_bytes=None,
                timeout=SEALED_REMOTE_CONTROL_TIMEOUT_SECONDS,
                allow_stdout=False,
            )
            stdout = self._invoke(
                connection,
                execute,
                input_bytes=None,
                timeout=plan.timeout_seconds + SEALED_REMOTE_TIMEOUT_MARGIN_SECONDS,
                allow_stdout=True,
            )
            try:
                rendered = stdout.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SealedRemoteError("sealed remote aggregate is not UTF-8") from exc
            verified = verify_sealed_aggregate(rendered, expected_challenge=plan.challenge)
            if verified.get("ok") is not True:
                raise SealedRemoteError("sealed remote aggregate failed verification")
            envelope = rendered
        except SealedRemoteError as exc:
            operation_error = exc
        finally:
            try:
                self._invoke(
                    connection,
                    cleanup,
                    input_bytes=None,
                    timeout=SEALED_REMOTE_CONTROL_TIMEOUT_SECONDS,
                    allow_stdout=False,
                )
            except SealedRemoteError as exc:
                cleanup_error = exc

        if operation_error is not None:
            raise SealedRemoteError("sealed remote execution failed") from operation_error
        if cleanup_error is not None:
            raise SealedRemoteError("sealed remote cleanup failed") from cleanup_error
        if envelope is None:
            raise SealedRemoteError("sealed remote execution failed")
        return envelope
