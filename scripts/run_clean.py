"""CLI: gate whether a replay artifact completed without recorded errors.

  python -m scripts.run_clean result.json
  python -m scripts.run_clean result.json --strict

``--strict``: exit 1 when any error is present (CI gate). Without ``--strict``, prints the
report and exits 0.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.run_clean import check_run_clean, run_clean_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw traceback: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``.
    Mirrors the merged ``generalization_gate`` (#1446) / ``objective_integrity`` (#1377) CLIs.
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
    except json.JSONDecodeError as exc:
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate whether a replay artifact has no errors")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when errors are present (CI gate)")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    result = check_run_clean(artifact)
    print(run_clean_headline(result), file=sys.stderr)
    print(json.dumps(result, indent=2))
    if args.strict and not result["passed"]:
        return 1
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
