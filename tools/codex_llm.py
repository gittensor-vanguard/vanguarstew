"""codex / OAuth LLM backend — DEVELOPMENT & MAINTENANCE ONLY.

This duck-types `agent.llm.LLM` (`.model`, `.offline`, `.chat`, `.chat_json`) so it can drive
the benchmark and maintenance tooling from a locally-authenticated `codex` CLI (ChatGPT / OAuth,
e.g. gpt-5.5) **without an API key** — handy for exploring the benchmark or running a strong
model against a live PR when you don't have managed inference on hand.

IMPORTANT — this is NOT for scored inference. The validator-scored agent path (`agent.solve`
via `agent.llm.LLM`) MUST use only the validator-supplied `model` / `api_base` / `api_key`, per
the managed-inference contract documented in `agent/llm.py` (the same rule ninja follows). `codex`
is a third-party provider, so it is intentionally kept OUT of that path and lives here in `tools/`.
Use it for local development only — never to produce a scored submission.

Requires the `codex` CLI on PATH and a completed `codex login`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from agent.llm import extract_json


class CodexError(RuntimeError):
    """Raised when the `codex` CLI is unavailable or cannot be invoked."""


class CodexLLM:
    """An `agent.llm.LLM`-compatible backend backed by `codex exec` (local OAuth).

    Args:
        model:   codex model id (e.g. "gpt-5.5"); None uses the codex default.
        timeout: seconds to wait for a completion before aborting.
        effort:  optional `model_reasoning_effort` (e.g. "low"/"medium"/"high").
    """

    def __init__(self, model=None, timeout=480, effort=None):
        self.model = model
        self.timeout = timeout
        self.effort = effort
        self.offline = False  # this backend always calls codex; there is no offline stub

    @staticmethod
    def available() -> bool:
        """True if the `codex` CLI is on PATH."""
        return shutil.which("codex") is not None

    def chat(self, system: str, user: str) -> str:
        """Single-turn completion. Runs `codex exec` read-only and returns its last message."""
        if not self.available():
            raise CodexError(
                "the `codex` CLI is not on PATH — install it and run `codex login`. "
                "This backend is for local development only, not scored inference."
            )
        prompt = (
            f"{system}\n\n{user}\n\n"
            "Respond with ONLY the requested JSON — no prose, no code fences."
        )
        fd, out = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        try:
            args = ["codex", "exec", "--skip-git-repo-check", "--ephemeral",
                    "-s", "read-only", "-o", out]
            if self.model:
                args += ["-m", self.model]
            if self.effort:
                args += ["-c", f"model_reasoning_effort={self.effort}"]
            args.append(prompt)
            try:
                subprocess.run(args, capture_output=True, text=True,
                               timeout=self.timeout, cwd=tempfile.gettempdir(), check=False)
            except subprocess.TimeoutExpired as exc:
                raise CodexError(f"codex timed out after {self.timeout}s") from exc
            with open(out, encoding="utf-8") as f:
                return f.read().strip()
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass

    def chat_json(self, system: str, user: str, stub=None):
        """Completion parsed as JSON. `stub` is accepted for parity with `agent.llm.LLM`
        (unused here — this backend is never offline)."""
        return extract_json(self.chat(system, user))
