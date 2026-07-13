"""CLI: print a compact JSON summary of a replay artifact.

  python -m scripts.artifact_snapshot result.json
  python -m scripts.artifact_snapshot tuned.json held_out.json   # one snapshot per file

Loads each ``run_eval --out`` JSON artifact and prints a stable machine-readable snapshot to
stdout (kind, headline score, task/repo counts, error/offline flags). A one-line headline is
written to stderr for quick CI logging.
"""

from __future__ import annotations

import argparse
import json
import sys

from benchmark.artifact_snapshot import snapshot, snapshot_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are handled distinctly so the user gets an actionable
    message instead of a raw traceback: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``
    (e.g. an I/O error, whose message is echoed). Mirrors the merged ``generalization_gate``
    (#1446) / ``objective_integrity`` (#1377) CLIs.
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
    """Parse ``argv``, print snapshot(s), and return the intended exit code."""
    ap = argparse.ArgumentParser(description="Print a compact JSON summary of replay artifact(s)")
    ap.add_argument("artifacts", nargs="+", help="one or more run_eval --out JSON artifacts")
    args = ap.parse_args(argv)

    outputs = []
    for path in args.artifacts:
        try:
            artifact = load_artifact(path)
        except SystemExit as exc:
            return int(exc.code)
        summary = snapshot(artifact)
        print(snapshot_headline(summary), file=sys.stderr)
        if len(args.artifacts) == 1:
            print(json.dumps(summary, indent=2))
            return 0
        outputs.append({"path": path, "snapshot": summary})

    print(json.dumps(outputs, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
