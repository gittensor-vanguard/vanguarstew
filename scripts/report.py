"""CLI: render a saved ``run_eval --out`` JSON artifact as Markdown.

  python -m scripts.report result.json
  python -m scripts.report result.json --out report.md
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.report import DEFAULT_GAP_INSPECT_THRESHOLD, render_report


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except UnicodeDecodeError as exc:
        # Non-UTF-8 mid-read: keep a distinct message (UnicodeDecodeError subclasses
        # ValueError, so this arm must come first).
        print(f"artifact is not valid UTF-8 JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Render a run_eval --out JSON artifact as Markdown")
    ap.add_argument("artifact", help="saved replay result JSON")
    ap.add_argument("--out", default=None, help="write Markdown to this path (default: stdout)")
    ap.add_argument("--gap-threshold", type=float, default=DEFAULT_GAP_INSPECT_THRESHOLD,
                    help="generalization gap above this value yields an inspect verdict "
                         f"(default {DEFAULT_GAP_INSPECT_THRESHOLD})")
    args = ap.parse_args()

    # load_artifact prints a clean message and raises SystemExit(1) on any bad path or
    # bad JSON, so main() needs no error handling of its own here.
    artifact = load_artifact(args.artifact)

    md = render_report(artifact, gap_inspect_threshold=args.gap_threshold)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        print(md, end="")


if __name__ == "__main__":
    main()
