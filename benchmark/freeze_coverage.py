"""Summarize how many per-repo rows carry a freeze commit.

``freeze_digest`` fingerprints repo identities and freeze commits; this utility reports the
fraction of per-repo rows that actually pinned a ``freeze_commit`` — useful when auditing whether
a multi-repo run froze every repo it touched.

Pure analysis: no I/O, never mutates its input, and malformed ``per_repo`` rows are logged and
skipped rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _rows_from_per_repo(per_repo, field: str = "per_repo") -> list[dict]:
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "freeze_coverage: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    rows = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "freeze_coverage: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        rows.append(entry)
    return rows


def _has_freeze_commit(entry: dict) -> bool:
    value = entry.get("freeze_commit")
    return isinstance(value, str) and bool(value)


def _slice_summary(per_repo, field: str = "per_repo") -> dict:
    rows = _rows_from_per_repo(per_repo, field)
    total = len(rows)
    frozen = sum(1 for row in rows if _has_freeze_commit(row))
    coverage = round(frozen / total, 3) if total > 0 else None
    return {
        "repos_total": total,
        "repos_frozen": frozen,
        "freeze_coverage": coverage,
    }


def summarize_freeze_coverage(artifact) -> dict:
    """Return freeze-commit coverage for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "single":
        frozen = 1 if _has_freeze_commit(artifact) else 0
        return {
            "kind": kind,
            "repos_total": 1,
            "repos_frozen": frozen,
            "freeze_coverage": float(frozen),
            "partitions": None,
        }
    if kind == "multi":
        stats = _slice_summary(artifact.get("per_repo"))
        return {"kind": kind, **stats, "partitions": None}
    if kind == "generalization":
        partitions = {}
        totals = frozen = 0
        for name in ("tuned", "held_out"):
            part = _dict(artifact.get(name))
            stats = _slice_summary(part.get("per_repo"), f"{name}.per_repo")
            partitions[name] = stats
            totals += stats["repos_total"]
            frozen += stats["repos_frozen"]
        coverage = round(frozen / totals, 3) if totals > 0 else None
        return {
            "kind": kind,
            "repos_total": totals,
            "repos_frozen": frozen,
            "freeze_coverage": coverage,
            "partitions": partitions,
        }
    return {
        "kind": kind,
        "repos_total": 0,
        "repos_frozen": 0,
        "freeze_coverage": None,
        "partitions": None,
    }


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def freeze_coverage_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_freeze_coverage` result."""
    summary = _dict(summary)
    total = summary.get("repos_total")
    if not _is_int(total) or total <= 0:
        return "freeze coverage: no per-repo rows"
    if summary.get("kind") == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        return (
            f"freeze coverage: {_fmt_rate(summary.get('freeze_coverage'))} "
            f"({summary.get('repos_frozen')}/{total}) "
            f"[tuned {_fmt_rate(tuned.get('freeze_coverage'))}, "
            f"held-out {_fmt_rate(held.get('freeze_coverage'))}]"
        )
    return (
        f"freeze coverage: {_fmt_rate(summary.get('freeze_coverage'))} "
        f"({summary.get('repos_frozen')}/{total})"
    )
