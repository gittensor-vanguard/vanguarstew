"""Build a stable freeze digest from a replay artifact's per-repo rows.

``comparability`` checks whether two artifacts name the same repos; ``freeze_digest`` captures
the repo identities *and* freeze commits from a single artifact as a sorted, JSON-friendly
fingerprint for logging or cache keys.

Pure analysis: no I/O, never mutates its input, and malformed ``per_repo`` rows are logged and
skipped rather than raising.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _repo_key(entry: dict) -> str:
    for key in ("repo_path", "url", "repo", "name", "repo_name"):
        value = entry.get(key)
        if value:
            return str(value)
    freeze = entry.get("freeze_commit")
    if isinstance(freeze, str) and freeze:
        return freeze[:10]
    return repr(sorted(entry.keys()))


def _freeze_commit(entry: dict) -> str | None:
    value = entry.get("freeze_commit")
    return value if isinstance(value, str) and value else None


def _rows_from_per_repo(per_repo, field: str = "per_repo") -> list[dict]:
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "freeze_digest: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "freeze_digest: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _collect_rows(artifact: dict) -> list[tuple[str, dict]]:
    kind = artifact_kind(artifact)
    if kind == "generalization":
        rows = []
        for partition in ("tuned", "held_out"):
            part = _dict(artifact.get(partition))
            for entry in _rows_from_per_repo(part.get("per_repo"), f"{partition}.per_repo"):
                rows.append((partition, entry))
        return rows
    if kind == "multi":
        return [("multi", entry) for entry in _rows_from_per_repo(artifact.get("per_repo"))]
    return []


def freeze_digest(artifact) -> dict:
    """Return a stable digest of repo identities and freeze commits."""
    artifact = _dict(artifact)
    entries = []
    for partition, row in _collect_rows(artifact):
        entries.append({
            "partition": partition,
            "repo": _repo_key(row),
            "freeze_commit": _freeze_commit(row),
        })
    entries.sort(key=lambda item: (item["partition"], item["repo"], item["freeze_commit"] or ""))
    return {
        "kind": artifact_kind(artifact),
        "entries": entries,
        "count": len(entries),
    }


def freeze_digest_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`freeze_digest` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    count = summary.get("count")
    count_txt = str(count) if isinstance(count, int) and not isinstance(count, bool) else "n/a"
    return f"freeze digest: {kind} with {count_txt} entr{'y' if count == 1 else 'ies'}"
