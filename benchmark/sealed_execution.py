"""Approval-bound execution of a validated sealed bundle with aggregate-only output.

The workload runs as the SSH account inside fresh Linux user, network, IPC, UTS, mount, and PID
namespaces.  It receives a minimal environment, no inherited credentials, no stdin, a bounded
regular-file stdout sink, and no observable stderr.  Only a verified ``sealed-aggregate-v1``
envelope is returned.

This is egress and output minimization for trusted application code, not an adversarial filesystem
sandbox.  The host filesystem is still mounted in the new mount namespace.  The Polaris boot
receipt also does not bind this uploaded bundle or its output.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Linux-only live surface
    resource = None

from benchmark.sealed_aggregate import (
    SEALED_AGGREGATE_CONTRACT,
    build_sealed_aggregate,
    verify_sealed_aggregate,
)
from benchmark.sealed_bundle import (
    SEALED_BUNDLE_MAX_ARCHIVE_BYTES,
    SealedBundleError,
    extract_sealed_bundle,
    inspect_sealed_bundle,
)

SEALED_EXECUTION_VERSION = 1
SEALED_EXECUTION_MIN_TIMEOUT_SECONDS = 1
SEALED_EXECUTION_MAX_TIMEOUT_SECONDS = 60 * 60
SEALED_EXECUTION_MIN_OUTPUT_BYTES = 1024
SEALED_EXECUTION_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
SEALED_EXECUTION_MIN_MEMORY_BYTES = 128 * 1024 * 1024
SEALED_EXECUTION_MAX_MEMORY_BYTES = 8 * 1024 * 1024 * 1024
SEALED_EXECUTION_NETWORK_POLICY = "new-linux-user-network-namespace-v1"
SEALED_EXECUTION_FILESYSTEM_POLICY = "trusted-payload-shared-host-mounts-v1"

_CHALLENGE_RE = re.compile(r"[0-9a-f]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ALLOWED_UNSHARE_PATHS = {Path("/usr/bin/unshare"), Path("/bin/unshare")}


class SealedExecutionError(RuntimeError):
    """A sealed execution plan, environment, workload, or result failed validation."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded_int(value, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SealedExecutionError(f"{label} is outside the allowed range")
    return value


def _restricted_parent(path: Path) -> Path:
    candidate = path.parent
    try:
        info = candidate.lstat()
    except OSError as exc:
        raise SealedExecutionError("cannot inspect sealed execution directory") from exc
    if not stat.S_ISDIR(info.st_mode) or candidate.is_symlink():
        raise SealedExecutionError("sealed execution directory must be a directory")
    if os.name != "nt" and info.st_mode & 0o077:
        raise SealedExecutionError("sealed execution directory permissions are too broad")
    return candidate


def _validate_public_executable(path: Path) -> Path:
    if path not in _ALLOWED_UNSHARE_PATHS:
        raise SealedExecutionError("network namespace tool path is not allowed")
    try:
        info = path.stat()
    except OSError as exc:
        raise SealedExecutionError("network namespace tool is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR or info.st_mode & 0o022:
        raise SealedExecutionError("network namespace tool is not trusted")
    return path


def _validate_helper(path: Path) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise SealedExecutionError("sealed execution helper is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or path.is_symlink() or info.st_mode & 0o022:
        raise SealedExecutionError("sealed execution helper is not trusted")
    return path


@dataclass(frozen=True)
class SealedExecutionPlan:
    """Network-free approval plan for one staged bundle execution."""

    bundle_path: Path
    challenge: str
    timeout_seconds: int = 900
    max_output_bytes: int = 8 * 1024 * 1024
    max_memory_bytes: int = 1024 * 1024 * 1024
    bundle_sha256: str = field(init=False)
    bundle_bytes: int = field(init=False)

    def __post_init__(self):
        if not isinstance(self.challenge, str) or not _CHALLENGE_RE.fullmatch(self.challenge):
            raise SealedExecutionError("challenge must be 32 random bytes encoded as lowercase hex")
        _bounded_int(
            self.timeout_seconds,
            label="timeout_seconds",
            minimum=SEALED_EXECUTION_MIN_TIMEOUT_SECONDS,
            maximum=SEALED_EXECUTION_MAX_TIMEOUT_SECONDS,
        )
        _bounded_int(
            self.max_output_bytes,
            label="max_output_bytes",
            minimum=SEALED_EXECUTION_MIN_OUTPUT_BYTES,
            maximum=SEALED_EXECUTION_MAX_OUTPUT_BYTES,
        )
        _bounded_int(
            self.max_memory_bytes,
            label="max_memory_bytes",
            minimum=SEALED_EXECUTION_MIN_MEMORY_BYTES,
            maximum=SEALED_EXECUTION_MAX_MEMORY_BYTES,
        )
        try:
            path = Path(self.bundle_path)
            info = inspect_sealed_bundle(path)
        except (TypeError, SealedBundleError) as exc:
            raise SealedExecutionError("sealed execution bundle is invalid") from exc
        _restricted_parent(path)
        object.__setattr__(self, "bundle_path", path)
        object.__setattr__(self, "bundle_sha256", info.bundle_sha256)
        object.__setattr__(self, "bundle_bytes", info.bundle_bytes)

    def request_body(self) -> dict:
        return {
            "version": SEALED_EXECUTION_VERSION,
            "bundle_sha256": self.bundle_sha256,
            "bundle_bytes": self.bundle_bytes,
            "challenge": self.challenge,
            "timeout_seconds": self.timeout_seconds,
            "max_output_bytes": self.max_output_bytes,
            "max_memory_bytes": self.max_memory_bytes,
            "result_contract": SEALED_AGGREGATE_CONTRACT,
            "network_policy": SEALED_EXECUTION_NETWORK_POLICY,
            "filesystem_policy": SEALED_EXECUTION_FILESYSTEM_POLICY,
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.request_body()).encode("utf-8")).hexdigest()

    def approval_summary(self) -> dict:
        return {
            "execution_performed": False,
            "operation": "extract-run-aggregate-cleanup",
            "request": self.request_body(),
            "request_sha256": self.request_sha256(),
            "privacy": {
                "local_path_omitted": True,
                "archive_member_names_omitted": True,
                "minimal_environment": True,
                "inherited_credentials_removed": True,
                "network_namespace_required": True,
                "stderr_discarded": True,
                "stdout_aggregate_only": True,
                "workspace_cleanup_required": True,
            },
            "limitations": {
                "filesystem_is_not_an_adversarial_sandbox": True,
                "workload_is_not_quote_bound": True,
                "output_is_not_quote_bound": True,
            },
        }


def _resource_limits(max_output_bytes: int, max_memory_bytes: int, timeout_seconds: int):
    def apply_limits():
        if resource is None:
            return
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (max_output_bytes, max_output_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        cpu_limit = max(1, int(math.ceil(timeout_seconds)))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit, cpu_limit + 1))
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))

    return apply_limits


def _run_process(
    argv,
    *,
    output_path: Path,
    cwd: Path,
    env: dict,
    timeout_seconds: int,
    max_output_bytes: int,
    max_memory_bytes: int,
) -> int:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stdout_file:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=subprocess.DEVNULL,
                cwd=cwd,
                env=env,
                start_new_session=True,
                preexec_fn=_resource_limits(
                    max_output_bytes,
                    max_memory_bytes,
                    timeout_seconds,
                ),
            )
            try:
                return process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except OSError:
                    process.kill()
                process.wait()
                return 124
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _read_result(path: Path, max_output_bytes: int) -> str:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size <= 0
            or info.st_size > max_output_bytes
        ):
            raise SealedExecutionError("sealed workload result is invalid")
        chunks = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise SealedExecutionError("sealed workload result changed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise SealedExecutionError("sealed workload result changed while reading")
        raw = b"".join(chunks)
    except SealedExecutionError:
        raise
    except OSError as exc:
        raise SealedExecutionError("sealed workload result is unavailable") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SealedExecutionError("sealed workload result is not UTF-8") from exc


class SealedExecutor:
    """Execute exactly one approved plan and return only its canonical aggregate envelope."""

    def __init__(
        self,
        *,
        namespace_tool: Path = Path("/usr/bin/unshare"),
        helper_path: Path | None = None,
        process_executor=None,
        geteuid=None,
    ):
        self.namespace_tool = Path(namespace_tool)
        self.helper_path = (
            Path(helper_path)
            if helper_path
            else (Path(__file__).resolve().parents[1] / "scripts" / "sealed_network_exec.py")
        )
        self._process_executor = process_executor or _run_process
        self._geteuid = geteuid or getattr(os, "geteuid", lambda: 0)

    def execute_approved(
        self,
        plan: SealedExecutionPlan,
        *,
        approved_request_sha256: str,
    ) -> str:
        if not isinstance(plan, SealedExecutionPlan):
            raise SealedExecutionError("an exact sealed execution plan is required")
        if not _SHA256_RE.fullmatch(approved_request_sha256 or "") or not hmac.compare_digest(
            plan.request_sha256(), approved_request_sha256
        ):
            raise SealedExecutionError("approved request digest does not match the execution plan")
        if sys.platform != "linux" or self._geteuid() == 0:
            raise SealedExecutionError("sealed execution requires an unprivileged Linux account")
        namespace_tool = _validate_public_executable(self.namespace_tool)
        helper = _validate_helper(self.helper_path)
        try:
            current_info = inspect_sealed_bundle(plan.bundle_path)
        except SealedBundleError as exc:
            raise SealedExecutionError("sealed execution bundle is invalid") from exc
        if current_info.bundle_bytes > SEALED_BUNDLE_MAX_ARCHIVE_BYTES or not hmac.compare_digest(
            current_info.bundle_sha256, plan.bundle_sha256
        ):
            raise SealedExecutionError("sealed execution bundle changed after approval")

        parent = _restricted_parent(plan.bundle_path)
        try:
            with tempfile.TemporaryDirectory(prefix=".sealed-run-", dir=parent) as temporary:
                temporary_path = Path(temporary)
                os.chmod(temporary_path, 0o700)
                root = temporary_path / "root"
                entrypoint = extract_sealed_bundle(
                    plan.bundle_path,
                    root,
                    expected_bundle_sha256=plan.bundle_sha256,
                )
                home = temporary_path / "home"
                scratch = temporary_path / "tmp"
                home.mkdir(mode=0o700)
                scratch.mkdir(mode=0o700)
                output_path = temporary_path / "artifact.json"
                env = {
                    "HOME": str(home),
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                    "PATH": "/usr/bin:/bin",
                    "PYTHONHASHSEED": "0",
                    "SEALED_RESULT_CHALLENGE": plan.challenge,
                    "SOURCE_DATE_EPOCH": "0",
                    "TMPDIR": str(scratch),
                    "VANGUARSTEW_OFFLINE": "1",
                }
                argv = [
                    str(namespace_tool),
                    "--user",
                    "--map-root-user",
                    "--net",
                    "--ipc",
                    "--uts",
                    "--mount",
                    "--pid",
                    "--fork",
                    "--kill-child=SIGKILL",
                    "--mount-proc",
                    sys.executable,
                    str(helper),
                    "--root",
                    str(root),
                    "--entrypoint",
                    str(entrypoint),
                ]
                try:
                    returncode = self._process_executor(
                        argv,
                        output_path=output_path,
                        cwd=root,
                        env=env,
                        timeout_seconds=plan.timeout_seconds,
                        max_output_bytes=plan.max_output_bytes,
                        max_memory_bytes=plan.max_memory_bytes,
                    )
                except Exception as exc:
                    raise SealedExecutionError("sealed workload execution failed") from exc
                if returncode != 0:
                    raise SealedExecutionError("sealed workload execution failed")
                raw_artifact = _read_result(output_path, plan.max_output_bytes)
                try:
                    artifact = json.loads(raw_artifact)
                    envelope = build_sealed_aggregate(artifact, challenge=plan.challenge)
                except (ValueError, TypeError) as exc:
                    raise SealedExecutionError(
                        "sealed workload result failed the aggregate gate"
                    ) from exc
                verified = verify_sealed_aggregate(envelope, expected_challenge=plan.challenge)
                if verified.get("ok") is not True:
                    raise SealedExecutionError("sealed workload result failed the aggregate gate")
                return envelope
        except SealedExecutionError:
            raise
        except (OSError, SealedBundleError) as exc:
            raise SealedExecutionError("sealed execution workspace failed") from exc
