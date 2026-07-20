"""CLI: print decisive versus tie task shares from a replay artifact tally.

  python -m scripts.decisive_rate result.json

Exits 2 when the artifact path is missing, JSON is invalid, or the root value is not an object.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.decisive_rate import decisive_rate_headline, summarize_decisive_rate


def load_artifact(path: str) -> dict:
    """Load a JSON artifact from ``path``, exiting with a clean error on failure.

    Distinguishes the specific ``OSError`` subclasses ``open()`` raises for a bad path so the
    user gets an actionable message rather than a raw traceback: a broken symlink (dangling
    target), a symlink loop, ``FileNotFoundError`` (missing), ``PermissionError`` (unreadable --
    including a directory on Windows), ``IsADirectoryError`` (a directory), and
    ``NotADirectoryError`` (a path component is not a directory). Any other ``OSError`` (a real
    I/O error) keeps its underlying text with a clean exit rather than a raw traceback.

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
        # A symlink loop raises OSError(ELOOP), which none of the arms above catch -- it used to
        # escape load_artifact as a raw traceback (exit 1), not the clean exit 2 this CLI intends.
        # Any other real read failure keeps its underlying text rather than a bare errno traceback.
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
    ap = argparse.ArgumentParser(description="Summarize decisive versus tie task shares from tally")
    ap.add_argument("artifact", help="run_eval --out JSON artifact")
    args = ap.parse_args(argv)
    try:
        artifact = load_artifact(args.artifact)
    except SystemExit as exc:
        return int(exc.code)
    summary = summarize_decisive_rate(artifact)
    print(decisive_rate_headline(summary), file=sys.stderr)
    print(json.dumps(summary, indent=2))
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
