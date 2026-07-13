"""CLI: gate whether several replay artifacts are on the same benchmark surface.

  python -m scripts.comparability runA.json runB.json runC.json
  python -m scripts.comparability --strict agentA.json agentB.json

Loads two or more ``run_eval --out`` JSON artifacts and verifies they share the same artifact
kind (single / multi / generalization) and, when applicable, the same ``per_repo`` repo set.
Prints the JSON report to stdout and a one-line headline to stderr.

``--strict``: exit with code 1 when any check fails (for CI gating before leaderboard or
``compare_eval``). Without ``--strict``, the report is printed and the process exits 0 even when
the artifacts are not comparable.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.comparability import check_comparability, comparability_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw traceback: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    """Parse ``argv``, evaluate the gate, print the report, and return the intended exit code."""
    ap = argparse.ArgumentParser(
        description="Gate whether replay artifacts are on the same benchmark surface",
    )
    ap.add_argument("artifacts", nargs="+", help="two or more run_eval --out JSON artifacts")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when artifacts are not comparable (CI gate before leaderboard/compare)",
    )
    args = ap.parse_args(argv)

    try:
        loaded = [load_artifact(path) for path in args.artifacts]
    except SystemExit as exc:
        return int(exc.code)

    result = check_comparability(loaded)
    print(comparability_headline(result), file=sys.stderr)
    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
