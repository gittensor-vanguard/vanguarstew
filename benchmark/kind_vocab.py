"""Shared maintainer-kind vocabulary for plan items and commit subjects.

``benchmark.score`` uses these tables for ``commit_kind`` / ``plan_kind`` and the
``kind_recall`` objective anchor. Keeping the aliases in one module prevents silent
drift between the planner's plan kinds and the conventional-commit prefixes the scorer
recognizes in revealed history.
"""

from __future__ import annotations

# Plan-only maintainer actions — not commit kinds, so they never map for kind_recall.
PLAN_ONLY_KINDS = frozenset({"triage"})

# Conventional-commit type prefix (and common synonyms) -> normalized maintainer kind.
COMMIT_PREFIX_KIND = {
    "feat": "feat", "feature": "feat",
    "fix": "fix", "bugfix": "fix", "bug": "fix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "perf": "perf",
    "test": "test", "tests": "test",
    "build": "build", "deps": "chore", "dep": "chore",
    "ci": "ci",
    "chore": "chore",
    "style": "style",
    "revert": "revert",
    "release": "release",
}

# Planner plan-item ``kind`` field -> the same normalized kinds as ``COMMIT_PREFIX_KIND``.
PLAN_ITEM_KIND = {
    "feature": "feat", "feat": "feat",
    "bugfix": "fix", "fix": "fix", "bug": "fix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "perf": "perf",
    "test": "test", "tests": "test",
    "release": "release",
    "dep": "chore", "deps": "chore", "chore": "chore",
    "build": "build",
    "ci": "ci",
    "style": "style",
    "revert": "revert",
}


def normalize_commit_prefix(prefix: str) -> str | None:
    """Map a conventional-commit type token to a normalized kind, or None."""
    return COMMIT_PREFIX_KIND.get((prefix or "").strip().lower())


def normalize_plan_kind(kind: str) -> str | None:
    """Map a plan item's ``kind`` to a normalized commit kind, or None."""
    key = (kind or "").strip().lower()
    if not key or key in PLAN_ONLY_KINDS:
        return None
    return PLAN_ITEM_KIND.get(key)


def plan_aliases_for_commit_prefix(prefix: str) -> set[str]:
    """Plan-item kind strings that normalize to the same kind as ``prefix``."""
    target = normalize_commit_prefix(prefix)
    if target is None:
        return set()
    return {alias for alias, norm in PLAN_ITEM_KIND.items() if norm == target}


def shared_normalized_kinds() -> set[str]:
    """Normalized kinds reachable from both plan items and commit prefixes."""
    return set(COMMIT_PREFIX_KIND.values()) & set(PLAN_ITEM_KIND.values())
