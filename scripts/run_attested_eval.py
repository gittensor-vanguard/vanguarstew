"""Run one public deterministic replay and emit its canonical Polaris stdout envelope.

This is the workload entrypoint for the Phase 1 eval image.  Successful stdout contains exactly
one canonical JSON envelope; diagnostics and failures go to stderr.  The command is intentionally
limited to public GitHub inputs.  A future sealed-input flow needs a separate aggregate-only output
contract and must not reuse this command, because the benchmark artifact can expose repo-derived
details.

Recorded-transcript mode starts the existing replay proxy on loopback and makes every model call
consume the committed transcript.  ``--offline-stub`` is an explicit development mode: it uses the
deterministic built-in stub and identifies that stub as the transcript input rather than pretending
a model transcript was replayed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
from contextlib import contextmanager

from benchmark.attestation import build_evidence
from benchmark.baselines import BASELINES, DEFAULT_BASELINE
from benchmark.memory import BenchmarkMemoryProvider, MemoryError, MemoryStore
from benchmark.polaris import build_stdout_envelope
from benchmark.runner import run_replay
from benchmark.transcript import TranscriptStore
from scripts.transcript_proxy import build_server

_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")
_IMAGE_RE = re.compile(r"[^\s]+@sha256:[0-9a-fA-F]{64}")
_MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}")
_PUBLIC_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GITHUB_HTTPS_RE = re.compile(
    r"https://github\.com/(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_GITHUB_SSH_RE = re.compile(
    r"(?:ssh://git@github\.com/|git@github\.com:)(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)
_OFFLINE_TRANSCRIPT = TranscriptStore().digest()


class AttestedEvalError(RuntimeError):
    """A public-input or deterministic-replay precondition failed."""


def _git(repo: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise AttestedEvalError("cannot identify the public repository input") from exc
    return result.stdout.strip()


def _origin_slug(repo: str) -> str:
    origin = _git(repo, "remote", "get-url", "origin")
    match = _GITHUB_HTTPS_RE.fullmatch(origin) or _GITHUB_SSH_RE.fullmatch(origin)
    if not match:
        raise AttestedEvalError("repository origin is not a canonical GitHub URL")
    return match.group("slug").lower()


def _public_repo_identity(repo: str, public_repo: str) -> str:
    if not _PUBLIC_REPO_RE.fullmatch(public_repo or ""):
        raise AttestedEvalError("public repository must be an owner/name GitHub slug")
    if _origin_slug(repo) != public_repo.lower():
        raise AttestedEvalError("public repository slug does not match the mounted origin")
    commit = _git(repo, "rev-parse", "--verify", "HEAD")
    if not _COMMIT_RE.fullmatch(commit):
        raise AttestedEvalError("repository HEAD is not a full commit id")
    return f"github.com/{public_repo.lower()}@{commit.lower()}"


@contextmanager
def _offline_mode(enabled: bool):
    previous = os.environ.get("VANGUARSTEW_OFFLINE")
    os.environ["VANGUARSTEW_OFFLINE"] = "1" if enabled else "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("VANGUARSTEW_OFFLINE", None)
        else:
            os.environ["VANGUARSTEW_OFFLINE"] = previous


@contextmanager
def _replay_endpoint(transcript_path: str):
    try:
        store = TranscriptStore.load(transcript_path)
    except (OSError, ValueError) as exc:
        raise AttestedEvalError("cannot load the replay transcript") from exc
    if not len(store):
        raise AttestedEvalError("recorded-transcript mode requires at least one response")

    server = build_server("replay", 0, store=store)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        yield f"http://127.0.0.1:{port}/v1", store.digest()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _positive(value: int, label: str) -> int:
    if value <= 0:
        raise AttestedEvalError(f"{label} must be positive")
    return value


def _benchmark_memory(args):
    """Open the optional trusted local memory controller for a public replay.

    The store is never serialized into the workload result.  The provider itself emits only a
    public, task-scoped benchmark view, and the runner binds its digest-only commitment.
    """
    mode = getattr(args, "memory_mode", "disabled")
    store_path = getattr(args, "memory_store", None)
    if mode == "disabled":
        if store_path:
            raise AttestedEvalError("memory store requires --memory-mode benchmark")
        return None, None
    if mode != "benchmark" or not store_path:
        raise AttestedEvalError("benchmark memory requires a local controller store")
    store = None
    try:
        store = MemoryStore(store_path).open()
        provider = BenchmarkMemoryProvider(
            store,
            repository_id=args.public_repo.lower(),
            public_only=True,
        )
    except (MemoryError, OSError) as exc:
        if store is not None:
            store.close()
        raise AttestedEvalError("cannot open the benchmark memory controller") from exc
    return store, provider


def run(args) -> str:
    """Return the canonical public-run envelope described by parsed CLI ``args``."""
    repo_identity = _public_repo_identity(args.repo, args.public_repo)
    if not _COMMIT_RE.fullmatch(args.agent_commit or ""):
        raise AttestedEvalError("agent commit must be a full 40-hex commit id")
    if not _IMAGE_RE.fullmatch(args.eval_image or ""):
        raise AttestedEvalError("eval image must be pinned by a sha256 content digest")
    if not _MODEL_RE.fullmatch(args.model or ""):
        raise AttestedEvalError("model must be a pinned snapshot identifier")
    if args.offline_stub != (args.model == "offline-stub-v1"):
        raise AttestedEvalError("model identifier does not match the selected replay mode")
    _positive(args.tasks, "tasks")
    _positive(args.horizon, "horizon")

    common = {
        "repo_path": args.repo,
        "agent_file": args.agent,
        "n_tasks": args.tasks,
        "horizon": args.horizon,
        "model": args.model,
        "seed": args.seed,
        "rotation_seed": args.rotation_seed,
        "baseline": args.baseline,
    }
    memory_store, memory_provider = _benchmark_memory(args)
    if memory_provider is not None:
        common["memory_provider"] = memory_provider
    try:
        if args.offline_stub:
            with _offline_mode(True):
                artifact = run_replay(api_base=None, api_key="offline", **common)
            transcript_digest = _OFFLINE_TRANSCRIPT
        else:
            with _replay_endpoint(args.transcript) as (api_base, transcript_digest):
                with _offline_mode(False):
                    artifact = run_replay(
                        api_base=api_base,
                        api_key="transcript-replay",
                        **common,
                    )
    finally:
        if memory_store is not None:
            memory_store.close()

    tasks = artifact.get("tasks") if isinstance(artifact, dict) else None
    if isinstance(tasks, bool) or not isinstance(tasks, int) or tasks <= 0:
        raise AttestedEvalError("replay did not produce a scored artifact")

    evidence = build_evidence(
        artifact,
        {
            "repo_set": repo_identity,
            "repo_set_partition": "public",
            "seed": args.seed,
            "rotation_seed": args.rotation_seed,
            "model": args.model,
            "agent_commit": args.agent_commit.lower(),
            "eval_image": args.eval_image,
            "transcript_digest": transcript_digest,
            # The replay may run with the trusted time-safe memory provider.  Only its
            # aggregate digest commitment is bound into the receipt; no view or store content
            # is included in this CLI envelope.
            "memory_commitment": artifact.get("memory_commitment"),
        },
    )
    return build_stdout_envelope(artifact, evidence)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="mounted checkout of the public repository")
    parser.add_argument(
        "--public-repo",
        required=True,
        help="public GitHub owner/name; must match the checkout's origin",
    )
    parser.add_argument("--agent", default="agent.py", help="agent entrypoint inside the image")
    parser.add_argument("--agent-commit", required=True, help="full source commit built into image")
    parser.add_argument("--eval-image", required=True, help="image reference pinned by @sha256")
    parser.add_argument("--model", required=True, help="pinned model snapshot identifier")
    parser.add_argument("--tasks", type=int, default=3)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rotation-seed", type=int, default=0)
    parser.add_argument("--baseline", choices=sorted(BASELINES), default=DEFAULT_BASELINE)
    parser.add_argument(
        "--memory-mode",
        choices=("disabled", "benchmark"),
        default="disabled",
        help="explicit memory mode; disabled keeps the historical replay stateless",
    )
    parser.add_argument(
        "--memory-store",
        help="trusted local SQLite controller path; required only for --memory-mode benchmark",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--transcript", help="recorded model transcript to replay on loopback")
    mode.add_argument(
        "--offline-stub",
        action="store_true",
        help="development-only deterministic stub; not a recorded model replay",
    )
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        stdout = run(args)
    except Exception:
        # Polaris may return workload diagnostics with a receipt.  Keep paths, transcript content,
        # remote errors, and operator details out of that surface; callers only need a fail-closed
        # status here and can reproduce locally for a detailed traceback.
        print("attested eval failed", file=sys.stderr)
        return 1
    sys.stdout.write(stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
