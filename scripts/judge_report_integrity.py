"""CLI: gate whether a replay artifact's judge summary matches its telemetry.

  python -m scripts.judge_report_integrity result.json
  python -m scripts.judge_report_integrity result.json --strict

With --strict the process exits non-zero when the judge summary is inconsistent.

Exit codes: ``0`` success (or a non-strict run), ``1`` a failed ``--strict`` gate, and ``2`` a
load error (the artifact path could not be read, or the JSON was invalid / not an object). The
distinct ``2`` lets a CI pipeline tell a bad artifact path from a gate failure.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sys

from benchmark.judge_report_integrity import check_judge_report_integrity, integrity_headline


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact, exiting with a clear message on a bad path or bad JSON.

    Each failure mode gets its own actionable message instead of a raw errno string: a broken
    symlink (dangling target), a symlink loop, a missing path, an unreadable file, a directory,
    a not-a-directory path component, invalid JSON, or a non-object root. Load errors exit 2 via
    ``SystemExit`` so CI can tell a bad path from a failed ``--strict`` gate (exit 1).

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        # open() has already failed. A single os.path.islink() lstat -- no pre-open exists()/
        # open() probe, so nothing here races with or precedes the real open() -- distinguishes a
        # dangling symlink (link present, target gone) from a genuinely missing path. islink()
        # swallows its own OSError (returns False), so it cannot raise, and it is only reached on
        # FileNotFoundError, never on the ELOOP path; it only refines the message text, so there
        # is no TOCTOU window that can change behavior. (Proven by test_islink_probe_is_not_
        # reachable_before_open_or_on_a_symlink_loop.)
        if os.path.islink(path):
            print(f"artifact is a broken symlink (target does not exist): {path}", file=sys.stderr)
        else:
            print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
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
        # distinctly; any other read failure keeps its strerror (or full text when there is
        # none) so the offending path is printed exactly once, with a clean exit.
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
        else:
            print(f"cannot read artifact ({path}): {getattr(exc, 'strerror', None) or exc}",
                  file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises JSONDecodeError (a ValueError) for malformed JSON, and a plain
        # ValueError for an integer literal beyond the int-string-conversion limit (py3.11+).
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Gate a replay artifact on judge-report integrity")
    ap.add_argument("artifact", help="path to a run_eval --out JSON artifact")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 when the judge report integrity gate fails (for CI gating); a load error exits 2, distinct from this gate exit")
    args = ap.parse_args()

    artifact = load_artifact(args.artifact)

    result = check_judge_report_integrity(artifact)
    print(integrity_headline(result), file=sys.stderr)
    for check in result["checks"]:
        mark = "PASS" if check["passed"] else "FAIL"
        print(f"  [{mark}] {check['name']}: {check['detail']}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    if args.strict and not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
