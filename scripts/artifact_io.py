"""Shared JSON-artifact loader for scripts/ CLIs.

Every artifact-consuming CLI used to ship its own near-copy of ``load_artifact``. The mature
ones (``decisive_rate``, ``component_mix``, …) implement a full path-error taxonomy with
exit 2; older gate CLIs still exited 1 on path failure (colliding with ``--strict``) and
misreported dangling symlinks / symlink loops. This module is the single source of that
taxonomy — import it instead of pasting another copy.
"""

from __future__ import annotations

import errno
import json
import os
import sys


def load_artifact(path: str) -> dict:
    """Load a JSON-object artifact from ``path``, exiting 2 with a clean message on failure.

    Distinguishes the specific ``OSError`` subclasses ``open()`` raises for a bad path so the
    user gets an actionable message rather than a raw traceback / errno string:

    - broken symlink (dangling target) — ``FileNotFoundError`` + ``os.path.islink``
    - missing file — ``FileNotFoundError``
    - unreadable (incl. a directory on Windows) — ``PermissionError``
    - directory — ``IsADirectoryError``
    - parent component is not a directory — ``NotADirectoryError``
    - symlink loop — ``OSError(ELOOP)``
    - any other read failure — ``OSError`` with its underlying text
    - invalid JSON / non-UTF-8 — ``ValueError`` / ``UnicodeDecodeError``
    - non-object root — explicit message

    Broken-symlink detection runs *after* ``open`` fails (``FileNotFoundError`` + ``islink``),
    so there is no ``exists``/``open`` TOCTOU pre-check that can raise on a symlink loop.

    Exit code is always **2**, distinct from the gating exit **1** used by ``--strict`` /
    ``--fail-on-regression`` on the consumer CLIs.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        # open() already failed; classify dangling symlink vs missing path without a prior
        # exists() probe (which can raise on a symlink loop and races with open).
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
        print(
            f"artifact path is not a file (a parent component is not a directory): {path}",
            file=sys.stderr,
        )
        raise SystemExit(2) from None
    except OSError as exc:
        # A symlink loop raises OSError(ELOOP), which none of the arms above catch.
        if getattr(exc, "errno", None) == errno.ELOOP:
            print(f"artifact path is a symlink loop: {path}", file=sys.stderr)
        else:
            # Prefer strerror so an OSError that already carries ``filename`` does not print the
            # path twice (once in the prefix, once inside ``str(exc)``).
            print(
                f"cannot read artifact ({path}): {getattr(exc, 'strerror', None) or exc}",
                file=sys.stderr,
            )
        raise SystemExit(2) from None
    except UnicodeDecodeError as exc:
        # Non-UTF-8 mid-read: keep a distinct message (UnicodeDecodeError subclasses
        # ValueError, so this arm must come first).
        print(f"artifact is not valid UTF-8 JSON ({path}): {exc}", file=sys.stderr)
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
