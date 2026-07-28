"""CLI: audit a frozen context JSON for residual forward-reference leaks.

  python -m scripts.audit_context path/to/.vanguarstew_context.json
  python -m scripts.audit_context path/to/context.json --strict   # exit 1 on any leak

Prints findings to stderr and the full JSON report on stdout. With ``--strict``, exits
non-zero when the context is not clean — a CI gate for leakage controls.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.leakage_audit import audit_context, audit_headline, is_clean


def load_context(path: str) -> dict:
    """Load a JSON-object context, exiting with a clear message on a bad path or bad JSON.

    Path problems get a specific, actionable message instead of a bare exception string: a
    broken symlink (dangling target), a symlink loop, ``FileNotFoundError`` (missing),
    ``PermissionError`` (unreadable -- including a directory on Windows), ``IsADirectoryError``
    (a directory on POSIX), and any other ``OSError``.

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        if os.path.islink(path):
            print(f"context is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"context not found: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except PermissionError:
        print(f"context is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except IsADirectoryError:
        print(f"context path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    except OSError as exc:
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"context path is a symlink loop: {path}", file=sys.stderr)
        else:
            print(f"cannot read context ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"context is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    if not isinstance(data, dict):
        print(f"context must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(1) from None
    return data


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit a frozen context for residual forward-reference leaks",
    )
    ap.add_argument("context", help="path to a frozen context JSON file")
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when the context is not clean (CI gating)",
    )
    args = ap.parse_args()

    context = load_context(args.context)

    findings = audit_context(context)
    report = {"clean": is_clean(context), "findings": findings}
    print(audit_headline(findings), file=sys.stderr)
    for row in findings:
        print(f"  {row['location']}: {row['value']!r} -> {row['masked']!r}", file=sys.stderr)
    print(json.dumps(report, indent=2))

    if args.strict and findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
