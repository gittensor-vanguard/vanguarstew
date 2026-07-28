"""Run an untrusted benchmark candidate in a locked-down, networkless Docker container."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows deployment is unsupported, import stays clean.
    resource = None

SANDBOX_IMAGE = (
    "python:3.12-slim@sha256:"
    "57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de"
)
SANDBOX_RESULT_MARKER = "VANGUARSTEW_SANDBOX_RESULT="
MAX_SANDBOX_OUTPUT_BYTES = 1024 * 1024


class DockerSolveError(RuntimeError):
    """The isolated candidate did not return a bounded valid result."""


def _safe_mount_path(path, *, kind: str) -> str:
    resolved = os.path.realpath(os.fspath(path))
    if not resolved or any(character in resolved for character in (",", "\n", "\x00")):
        raise DockerSolveError(f"{kind} path cannot be mounted safely")
    return resolved


class DockerSolveAdapter:
    """Callable ``run_replay(..., solve_fn=...)`` adapter for an untrusted checkout."""

    def __init__(self, *, candidate_root, broker_socket, trusted_entrypoint=None,
                 image=SANDBOX_IMAGE, timeout=180, executor=subprocess.run):
        self.candidate_root = _safe_mount_path(candidate_root, kind="candidate")
        self.broker_socket = _safe_mount_path(broker_socket, kind="broker")
        source_root = Path(__file__).resolve().parents[1]
        self.trusted_entrypoint = _safe_mount_path(
            trusted_entrypoint or source_root / "scripts" / "sandbox_candidate_entry.py",
            kind="entrypoint",
        )
        if not os.path.isdir(self.candidate_root):
            raise DockerSolveError("candidate root must be a directory")
        if not os.path.isfile(os.path.join(self.candidate_root, "agent.py")):
            raise DockerSolveError("candidate root does not contain agent.py")
        try:
            socket_mode = os.stat(self.broker_socket).st_mode
        except OSError as exc:
            raise DockerSolveError("broker socket is unavailable") from exc
        if not stat.S_ISSOCK(socket_mode):
            raise DockerSolveError("broker path is not a Unix socket")
        if not os.path.isfile(self.trusted_entrypoint):
            raise DockerSolveError("trusted sandbox entrypoint is unavailable")
        if not isinstance(image, str) or "@sha256:" not in image:
            raise DockerSolveError("sandbox image must be pinned by digest")
        self.image = image
        self.timeout = timeout
        self._executor = executor

    def _command(self, *, repo_path, request_path) -> list[str]:
        repo = _safe_mount_path(repo_path, kind="frozen repository")
        request = _safe_mount_path(request_path, kind="request")
        return [
            "docker", "run", "--rm", "--network=none", "--read-only",
            "--user=65534:65534", "--cap-drop=ALL", "--security-opt=no-new-privileges",
            "--pids-limit=128", "--memory=768m", "--cpus=2",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--mount", f"type=bind,src={self.candidate_root},dst=/candidate,readonly",
            "--mount", f"type=bind,src={repo},dst=/workspace,readonly",
            "--mount", f"type=bind,src={self.broker_socket},dst=/broker/model.sock",
            "--mount", f"type=bind,src={request},dst=/input/request.json,readonly",
            "--mount", f"type=bind,src={self.trusted_entrypoint},dst=/runner.py,readonly",
            self.image, "python3", "-I", "/runner.py",
        ]

    def __call__(self, *, repo_path, request, model, api_base, api_key, n):
        del api_base, api_key  # Secrets and arbitrary endpoints never enter the candidate sandbox.
        payload = {"request": request, "model": model, "n": n}
        with tempfile.TemporaryDirectory(prefix="vanguarstew-solve-") as temporary:
            request_path = os.path.join(temporary, "request.json")
            descriptor = os.open(request_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, allow_nan=False)
            # This file contains no credential; the non-root container user needs read access.
            os.chmod(request_path, 0o444)
            output_path = os.path.join(temporary, "stdout")
            with open(output_path, "w+b") as output:
                def limit_output():
                    resource.setrlimit(resource.RLIMIT_FSIZE, (
                        MAX_SANDBOX_OUTPUT_BYTES, MAX_SANDBOX_OUTPUT_BYTES,
                    ))

                try:
                    completed = self._executor(
                        self._command(repo_path=repo_path, request_path=request_path),
                        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                        timeout=self.timeout, check=False, env={"PATH": os.environ.get("PATH", "")},
                        preexec_fn=limit_output if os.name == "posix" and resource else None,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    raise DockerSolveError("isolated candidate execution failed") from exc
                if completed.returncode != 0:
                    raise DockerSolveError("isolated candidate execution failed")
                output.seek(0)
                rendered = output.read(MAX_SANDBOX_OUTPUT_BYTES + 1).decode("utf-8", "replace")
        marker_lines = [
            line[len(SANDBOX_RESULT_MARKER):]
            for line in rendered.splitlines()
            if line.startswith(SANDBOX_RESULT_MARKER)
        ]
        if len(marker_lines) != 1:
            raise DockerSolveError("isolated candidate result framing is invalid")
        try:
            result = json.loads(marker_lines[0])
        except (TypeError, ValueError) as exc:
            raise DockerSolveError("isolated candidate returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise DockerSolveError("isolated candidate result must be an object")
        return result
