"""Summarize how many per-repo rows carry a freeze commit.

``freeze_digest`` fingerprints repo identities and freeze commits; this utility reports the
fraction of per-repo rows that actually pinned a ``freeze_commit`` — useful when auditing whether
a multi-repo run froze every repo it touched.

Pure analysis: no I/O, never mutates its input, and never raises on malformed input. A ``per_repo``
row that is a non-empty string is a corrupt/malformed entry — it pinned no ``freeze_commit``, so it
counts as a repo that was not frozen (mirroring how #1362 counts such a row as an errored repo in
``error_repo_share``); other non-dict rows carry no repo signal and are skipped.
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


def _has_freeze_commit(entry: dict) -> bool:
    value = entry.get("freeze_commit")
    return isinstance(value, str) and bool(value)


def _repo_freeze_flags(per_repo, field: str = "per_repo") -> list[bool]:
    """One "pinned a freeze commit" flag per countable repo in ``per_repo``.

    A dict row is flagged by whether it carries a ``freeze_commit``. A non-empty string row is a
    corrupt/malformed entry that pinned nothing, so it counts as an *unfrozen* repo (flag
    ``False``) — mirroring how #1362 counts such a row as an errored repo in
    ``error_repo_share._repo_error_flags``, so a corrupt repo can never inflate freeze coverage.
    Empty/whitespace strings and other non-dict/non-string entries carry no repo signal and are
    skipped, so they neither inflate nor deflate the denominator.
    """
    if per_repo is None:
        return []
    if not isinstance(per_repo, list):
        logger.warning(
            "freeze_coverage: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return []
    flags = []
    for idx, entry in enumerate(per_repo):
        if isinstance(entry, dict):
            flags.append(_has_freeze_commit(entry))
        elif isinstance(entry, str) and entry.strip():
            logger.warning(
                "freeze_coverage: %s[%s] is a corrupt string row; counting as unfrozen",
                field,
                idx,
            )
            flags.append(False)
    return flags


def _slice_summary(per_repo, field: str = "per_repo") -> dict:
    flags = _repo_freeze_flags(per_repo, field)
    total = len(flags)
    frozen = sum(1 for flag in flags if flag)
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
