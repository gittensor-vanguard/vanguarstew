"""Run a local aggregate-only coverage diagnostic for source-anchored memory."""

from __future__ import annotations

import argparse
import json
import sys
import time

from benchmark.memory import MemoryError, MemoryStore
from benchmark.memory_coverage import MemoryCoverageError, run_memory_coverage
from benchmark.source_memory import (
    SourceAnchoredBenchmarkProvider,
    SourceCorpusError,
    import_source_commit_corpus,
)


def run(args) -> dict:
    started = time.monotonic()
    with MemoryStore(args.memory_store or ":memory:") as store:
        corpus = import_source_commit_corpus(
            store, repo_path=args.repo, repository_id=args.memory_repository_id,
            max_events=args.source_corpus_events,
        )
        result = run_memory_coverage(
            args.repo,
            memory_provider=SourceAnchoredBenchmarkProvider(
                store, repository_id=args.memory_repository_id, max_items=args.memory_items,
            ),
            n_tasks=args.tasks,
            horizon=args.horizon,
            min_history=args.min_history,
            rotation_seed=args.rotation_seed,
            after=args.after,
            before=args.before,
            horizon_days=args.horizon_days,
        )
    return {
        "source_corpus": corpus,
        "source_corpus_and_coverage_seconds": round(time.monotonic() - started, 6),
        **result,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--memory-repository-id", required=True)
    parser.add_argument("--memory-store", default=None)
    parser.add_argument("--source-corpus-events", type=int, default=400)
    parser.add_argument("--memory-items", type=int, default=4)
    parser.add_argument("--tasks", type=int, default=8)
    parser.add_argument("--horizon", type=int, default=5)
    parser.add_argument("--min-history", type=int, default=10)
    parser.add_argument("--after", default=None)
    parser.add_argument("--before", default=None)
    parser.add_argument("--horizon-days", type=int, default=None)
    parser.add_argument("--rotation-seed", type=int, default=None)
    parser.add_argument("--out", default=None)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run(args)
    except (MemoryCoverageError, MemoryError, SourceCorpusError, RuntimeError, ValueError) as exc:
        print(f"memory coverage failed: {exc}", file=sys.stderr)
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
