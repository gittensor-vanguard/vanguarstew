"""CLI: validate a leakage-safe repo-set JSON config.

  python -m scripts.validate_repo_set benchmark/repo_sets/example.json
"""

from __future__ import annotations

import argparse
import sys

from benchmark.repo_set import RepoSetError, load_repo_set


def validate_repo_set_path(path: str) -> str:
    """Load and validate ``path``; return a short success summary."""
    repo_set = load_repo_set(path)
    tuned = len(repo_set.tuned())
    held_out = len(repo_set.held_out())
    return (
        f"ok: {path} ({repo_set.name or 'unnamed'}; "
        f"{len(repo_set)} repos: {tuned} tuned, {held_out} held-out)"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="validate a vanguarstew repo-set JSON config")
    ap.add_argument("config", help="path to a repo-set JSON file")
    args = ap.parse_args()
    try:
        summary = validate_repo_set_path(args.config)
    except RepoSetError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(summary)


if __name__ == "__main__":
    main()
