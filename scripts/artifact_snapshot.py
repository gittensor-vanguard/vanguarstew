"""CLI: print a compact JSON summary of a replay artifact.

  python -m scripts.artifact_snapshot result.json
  python -m scripts.artifact_snapshot tuned.json held_out.json   # one snapshot per file

Loads each ``run_eval --out`` JSON artifact and prints a stable machine-readable snapshot to
stdout (kind, headline score, task/repo counts, error/offline flags). A one-line headline is
written to stderr for quick CI logging.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.artifact_snapshot import snapshot, snapshot_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a raw traceback / errno string:
    a broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable — including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), and any other ``OSError``.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # A dangling symlink raises FileNotFoundError too; islink() separates it from a plain
        # missing path so the message names the real problem (the link exists, its target does not).
        if os.path.islink(path):
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        # Windows raises PermissionError (not IsADirectoryError) when ``path`` is a directory.
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except NotADirectoryError:
        print(f"artifact path is not a file (a parent component is not a directory): {path}",
              file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        # A symlink loop raises OSError(ELOOP), which none of the arms above catch. Name it
        # distinctly; any other real read failure keeps its underlying text with a clean exit.
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
        else:
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
