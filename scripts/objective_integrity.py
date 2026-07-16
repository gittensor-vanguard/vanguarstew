"""CLI: gate whether a replay artifact's per-task objective dicts are valid.

  python -m scripts.objective_integrity result.json
  python -m scripts.objective_integrity result.json --strict

With --strict the process exits non-zero when objective inputs are invalid.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.objective_integrity import (
    DEFAULT_TOLERANCE,
    check_objective_integrity,
    integrity_headline,
)


def load_artifact(path: str) -> dict:
    """Load a JSON artifact from ``path``, exiting with a clean error on failure.

    Distinguishes the common ``OSError`` subclasses so the user gets an actionable
    message rather than a raw traceback:

    - ``FileNotFoundError``: the path does not exist.
    - ``PermissionError``: the file exists but is not readable.
    - ``IsADirectoryError``: the path is a directory, not a file.
    - Other ``OSError``: the raw ``str(exc)`` is used (covers broken symlinks,
      I/O errors, etc.) without leaking internal details beyond the OS message.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
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


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gate a replay artifact on per-task objective integrity",
    )
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help=f"max allowed objective_mean delta (default {DEFAULT_TOLERANCE})")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the objective integrity gate fails (for CI gating)")
    args = ap.parse_args()

    result = check_objective_integrity(load_artifact(args.artifact), tolerance=args.tolerance)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
