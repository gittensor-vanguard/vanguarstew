"""CLI: gate whether a replay artifact completed without recorded errors.

  python -m scripts.run_clean result.json
  python -m scripts.run_clean result.json --strict

``--strict``: exit 1 when any error is present (CI gate). Without ``--strict``, prints the
report and exits 0.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.run_clean import check_run_clean, run_clean_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    The common ``OSError`` subclasses are reported distinctly so the user gets an actionable
    message instead of a raw traceback: ``FileNotFoundError`` (missing, or a broken symlink),
    ``PermissionError`` (unreadable), ``IsADirectoryError`` (a directory, not a file),
    ``NotADirectoryError`` (a path component is not a directory), a symlink loop
    (``OSError(ELOOP)``), and any other ``OSError``. Mirrors the merged ``artifact_snapshot`` /
    ``objective_integrity`` / ``agree_order_share`` CLIs.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that could itself raise on a symlink loop.
    ``islink`` is guarded too: if it hits a loop (``ELOOP``) it is named as one rather than
    degrading to the plain "not found" message.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # A dangling symlink also raises FileNotFoundError; islink() separates it from a plain
        # missing path so the message names the real problem (the link exists, its target does not).
        try:
            is_broken_symlink = os.path.islink(path)
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ELOOP:
                print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
            else:
                print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
            raise SystemExit(2) from None
        if is_broken_symlink:
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
        # A symlink loop raises OSError(ELOOP), which none of the arms above catch.
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
