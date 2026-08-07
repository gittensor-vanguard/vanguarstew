"""Run a local paired no-memory versus source-anchored-memory replay experiment.

The command never publishes results.  It creates an isolated controller store, imports a bounded
public-source corpus, then runs the same frozen tasks with and without the benchmark memory view.
Use a recorded/pinned model input for a formal claim; live calls are useful pilot measurements but
are not reproducible by themselves.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from benchmark.ablation import AblationError, run_paired_memory_ablation
from benchmark.memory import MemoryError, MemoryStore
from benchmark.source_memory import (
    SourceAnchoredBenchmarkProvider,
    SourceCorpusError,
    import_source_commit_corpus,
)


def _env_file_value(path: str, name: str) -> str | None:
    """Read one literal dotenv assignment without evaluating shell syntax or printing it."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError("--env-file cannot be read") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, value = stripped.partition("=")
        if separator != "=" or key.strip() != name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
            value = value[1:-1]
        return value or None
    return None


def resolve_api_key(api_key: str | None, api_key_env: str | None,
                    env_file: str | None = None) -> str | None:
    """Read an optional API key from one named environment variable, never stdout."""
    if api_key and api_key_env:
        raise ValueError("use either --api-key or --api-key-env, not both")
    if env_file and not api_key_env:
        raise ValueError("--env-file requires --api-key-env")
    if api_key_env:
        if not api_key_env.replace("_", "a").isalnum() or api_key_env[0].isdigit():
            raise ValueError("--api-key-env must name a shell environment variable")
        value = os.environ.get(api_key_env) or (
            _env_file_value(env_file, api_key_env) if env_file else None
        )
        if not value:
            raise ValueError("--api-key-env is unset or empty")
        return value
    return api_key


def run(args) -> dict:
    api_key = resolve_api_key(args.api_key, args.api_key_env, args.env_file)
    corpus_started = time.monotonic()
    with MemoryStore(args.memory_store or ":memory:") as store:
        corpus = import_source_commit_corpus(
            store,
            repo_path=args.repo,
            repository_id=args.memory_repository_id,
            max_events=args.source_corpus_events,
        )
        provider = SourceAnchoredBenchmarkProvider(
            store, repository_id=args.memory_repository_id, max_items=args.memory_items,
        )
        corpus_seconds = time.monotonic() - corpus_started
        result = run_paired_memory_ablation(
            args.repo,
            memory_provider=provider,
            agent_file=args.agent,
            n_tasks=args.tasks,
            horizon=args.horizon,
            model=args.model,
            api_base=args.api_base,
            api_key=api_key,
            seed=args.seed,
            rotation_seed=args.rotation_seed,
            min_history=args.min_history,
            after=args.after,
            before=args.before,
            horizon_days=args.horizon_days,
            dual_order_judge=not args.single_order_judge,
            min_pairs=args.min_pairs,
            min_effect=args.min_effect,
            alpha=args.alpha,
            bootstrap_samples=args.bootstrap_samples,
            bootstrap_seed=args.bootstrap_seed,
        )
    return {
        "source_corpus": corpus,
        "source_corpus_build_seconds": round(corpus_seconds, 6),
        **result,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="local public git repository to replay")
    parser.add_argument("--memory-repository-id", required=True,
                        help="stable controller identity for the local source corpus")
    parser.add_argument("--memory-store", default=None,
                        help="optional new/empty local SQLite corpus path (default: in-memory)")
    parser.add_argument("--source-corpus-events", type=int, default=400)
    parser.add_argument("--memory-items", type=int, default=4)
    parser.add_argument("--agent", default="agent.py")
    parser.add_argument("--tasks", type=int, default=6)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--min-history", type=int, default=10)
    parser.add_argument("--after", default=None)
    parser.add_argument("--before", default=None)
    parser.add_argument("--horizon-days", type=int, default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--api-base", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--api-key-env", default=None,
                        help="read the model credential from this environment variable")
    parser.add_argument("--env-file", default=None,
                        help="optional dotenv file; reads only --api-key-env without shell evaluation")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--rotation-seed", type=int, default=None)
    parser.add_argument("--single-order-judge", action="store_true")
    parser.add_argument("--min-pairs", type=int, default=6)
    parser.add_argument("--min-effect", type=float, default=0.05)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--bootstrap-samples", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=0)
    parser.add_argument("--out", default=None, help="write the local JSON report to this path")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (AblationError, MemoryError, SourceCorpusError, RuntimeError, ValueError) as exc:
        print(f"memory ablation failed: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(rendered)
                handle.write("\n")
        except OSError as exc:
            print(f"cannot write --out: {exc}", file=sys.stderr)
            return 1
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
