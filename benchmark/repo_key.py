"""Stable repo identity string for per-repo replay rows.

Shared by freeze_digest, comparability, compare_eval, and other consumers that join or
fingerprint rows from ``per_repo`` lists.
"""

from __future__ import annotations

_REPO_KEY_FIELDS = ("repo_path", "url", "repo", "name", "repo_name")


def repo_key(entry: dict) -> str:
    """Derive a stable string identity from a per-repo row.

    Checks ``repo_path``, ``url``, ``repo``, ``name``, and ``repo_name`` in order, then the
    first ten characters of ``freeze_commit``, then ``repr(sorted(entry.keys()))``.

    The terminal ``repr(sorted(...))`` fallback is a last-resort label for rows that carry no
    name fields and no freeze commit. Per-repo joins (e.g. in compare_eval) skip rows that fail
    to match rather than merging distinct repos under one key.
    """
    for key in _REPO_KEY_FIELDS:
        value = entry.get(key)
        if value:
            return str(value)
    freeze = entry.get("freeze_commit")
    if isinstance(freeze, str) and freeze:
        return freeze[:10]
    return repr(sorted(entry.keys()))
