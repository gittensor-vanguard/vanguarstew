"""Extract a compact machine-readable summary from a replay artifact.

``report`` renders Markdown for humans and ``trend.headline_score`` returns only the headline
number. This fills the gap with a stable JSON-friendly snapshot for CI logging, dashboards, and
artifact indexes: kind, headline score, task/repo counts, and error/offline flags.

Pure analysis: no I/O, never mutates its input, and tolerates missing or malformed fields by
returning ``None`` for unavailable values rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    # Non-finite floats survive a save/load round trip (json.dump writes NaN/Infinity and
    # json.load parses them back), but int() raises on them and a NaN/Infinity count is not
    # a usable value anyway -- treat them as malformed, like a missing or wrong-typed field,
    # matching row_integrity.py (#616/#927). math.isfinite also raises OverflowError for ints
    # too large for a float, which would crash int()/formatting the same way.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _per_repo_tasks(per_repo, field: str = "per_repo") -> int | None:
    """Sum numeric ``tasks`` from a ``per_repo`` list; skip malformed rows."""
    if per_repo is None:
        return None
    if not isinstance(per_repo, list):
        logger.warning(
            "artifact_snapshot: %s is %s, not a list; treating as no tasks",
            field,
            type(per_repo).__name__,
        )
        return None
    total = 0
    saw = False
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "artifact_snapshot: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        tasks = entry.get("tasks")
        if not _is_number(tasks):
            continue
        total += int(tasks)
        saw = True
    return total if saw else 0


def _task_total(artifact: dict) -> int | None:
    """Best-effort task count for any artifact shape."""
    top = artifact.get("tasks")
    if _is_number(top):
        return int(top)
    if artifact_kind(artifact) == "generalization":
        tuned = _per_repo_tasks(_dict(artifact.get("tuned")).get("per_repo"), "tuned.per_repo")
        held = _per_repo_tasks(_dict(artifact.get("held_out")).get("per_repo"), "held_out.per_repo")
        if tuned is None and held is None:
            return None
        return (tuned or 0) + (held or 0)
    return _per_repo_tasks(artifact.get("per_repo"))


def _repo_tally(artifact: dict) -> dict | None:
    """``{total, scored, skipped}`` when the artifact carries a coherent multi-repo tally."""
    repos = artifact.get("repos")
    scored = artifact.get("scored_repos")
    if not (_is_int(repos) and _is_int(scored)):
        return None
    if repos <= 0 or scored < 0 or scored > repos:
        return None
    skipped = artifact.get("skipped")
    if skipped is not None and not (_is_int(skipped) and skipped == repos - scored):
        return None
    return {"total": repos, "scored": scored, "skipped": repos - scored}


def _has_error(artifact: dict) -> bool:
    """True when the artifact or any scored partition/per-repo row reports an error."""
    if artifact.get("error"):
        return True
    kind = artifact_kind(artifact)
    if kind == "generalization":
        for part in ("tuned", "held_out"):
            if _dict(artifact.get(part)).get("error"):
                return True
        containers = [
            _dict(artifact.get("tuned")).get("per_repo"),
            _dict(artifact.get("held_out")).get("per_repo"),
        ]
    elif kind == "multi":
        containers = [artifact.get("per_repo")]
    else:
        return False
    for per_repo in containers:
        if not isinstance(per_repo, list):
            continue
        for entry in per_repo:
            if isinstance(entry, dict) and entry.get("error"):
                return True
    return False


def snapshot(artifact) -> dict:
    """Return a compact JSON-friendly summary of a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    score = headline_score(artifact)
    body = {
        "kind": kind,
        "headline_score": score,
        "scored": score is not None,
        "tasks": _task_total(artifact),
        "repos": None,
        "generalization_gap": artifact.get("generalization_gap")
        if _is_number(artifact.get("generalization_gap"))
        else None,
        "repo_set": artifact.get("repo_set") if isinstance(artifact.get("repo_set"), str) else None,
        "decisive_margin": artifact.get("decisive_margin")
        if _is_number(artifact.get("decisive_margin"))
        else None,
        "offline": artifact.get("offline") if isinstance(artifact.get("offline"), bool) else None,
        "has_error": _has_error(artifact),
    }
    if kind == "generalization":
        body["repos"] = _repo_tally(_dict(artifact.get("tuned")))
    elif kind == "multi":
        body["repos"] = _repo_tally(artifact)
    return body


def snapshot_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`snapshot` result."""
    summary = _dict(summary)
    kind = summary.get("kind") or "unknown"
    score = summary.get("headline_score")
    score_txt = f"{score:.3f}" if _is_number(score) else "n/a"
    tasks = summary.get("tasks")
    tasks_txt = str(tasks) if _is_number(tasks) else "n/a"
    err = "error" if summary.get("has_error") else "ok"
    return f"snapshot: {kind} headline={score_txt} tasks={tasks_txt} status={err}"
