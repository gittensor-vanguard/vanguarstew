"""Gate whether a multi-repo replay artifact's headline aggregates match its per-repo means.

``run_multi_replay`` averages each repo's ``composite_mean`` (and component means) into a
cross-repo headline. ``score_integrity`` verifies the headline blend is internally consistent;
``row_integrity`` checks per-task rows inside each repo. Nothing verifies the cross-repo
headline actually equals the unweighted mean of scored ``per_repo`` entries — a hand-edited
artifact could inflate the aggregate while per-repo scores tell a different story.

``check_aggregate_integrity(result)`` verifies, for each multi-repo slice (including
``--generalization`` partitions):

1. ``per_repo_present`` — a usable ``per_repo`` list is present;
2. ``scored_repos_matches`` — ``scored_repos`` equals the count of repos with ``tasks > 0``;
3. ``skipped_matches`` — ``skipped`` equals total repos minus scored repos;
4. ``composite_mean_matches_repos`` — headline ``composite_mean`` equals the mean of scored
   per-repo composites;
5. ``judge_mean_matches_repos`` / ``objective_mean_matches_repos`` — ``composite_parts`` means
   equal the per-repo component means.

Single-repo artifacts (no ``per_repo`` detail) are out of scope and fail ``artifact_shape``.

The companion ``scripts/aggregate_integrity.py`` exits non-zero when aggregates are inconsistent.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.002


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "aggregate_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _round3(value):
    return round(float(value), 3) if _is_number(value) else None


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "aggregate_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _scored_entries(per_repo: list) -> list:
    return [
        entry for entry in per_repo
        if _is_number(entry.get("tasks")) and int(entry["tasks"]) > 0
    ]


def _mean_field(entries: list, field: str, parts_key: str | None = None) -> float | None:
    values = []
    for entry in entries:
        if parts_key:
            parts = entry.get("composite_parts")
            value = parts.get(parts_key) if isinstance(parts, dict) else None
        else:
            value = entry.get(field)
        if _is_number(value):
            values.append(float(value))
    return _round3(sum(values) / len(values)) if values else None


def _aggregate_slices(result: dict) -> list[tuple[str, dict]]:
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and "per_repo" in part:
                slices.append((label, part))
        return slices
    if "per_repo" in result:
        return [("run", result)]
    return []


def _check_slice(label: str, slice_: dict, tolerance: float, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    per_repo = _per_repo_list(slice_.get("per_repo"))
    scored = _scored_entries(per_repo)
    add("per_repo_present", bool(per_repo), f"{len(per_repo)} per-repo entr{'y' if len(per_repo) == 1 else 'ies'}")

    scored_n = len(scored)
    headline_scored = slice_.get("scored_repos")
    add("scored_repos_matches",
        _is_number(headline_scored) and int(headline_scored) == scored_n,
        f"scored_repos {headline_scored} vs {scored_n} repo(s) with tasks > 0")

    total_repos = slice_.get("repos")
    skipped = slice_.get("skipped")
    expected_skipped = len(per_repo) - scored_n
    if _is_number(total_repos):
        add("repos_count_matches",
            int(total_repos) == len(per_repo),
            f"repos {total_repos} vs len(per_repo) {len(per_repo)}")
    if _is_number(skipped):
        add("skipped_matches", int(skipped) == expected_skipped,
            f"skipped {skipped} vs expected {expected_skipped}")

    repo_composite_mean = _mean_field(scored, "composite_mean")
    headline_composite = slice_.get("composite_mean")
    if repo_composite_mean is not None and _is_number(headline_composite):
        delta = _round3(float(headline_composite) - repo_composite_mean)
        add("composite_mean_matches_repos", delta is not None and abs(delta) <= tolerance,
            f"composite_mean {headline_composite} vs per-repo mean {repo_composite_mean} "
            f"(delta {delta})")
    else:
        add("composite_mean_matches_repos", False, "cannot compare composite_mean to per-repo mean")

    parts = slice_.get("composite_parts")
    judge_mean = _dict(parts).get("judge_mean")
    objective_mean = _dict(parts).get("objective_mean")
    repo_judge = _mean_field(scored, "", parts_key="judge_mean")
    repo_objective = _mean_field(scored, "", parts_key="objective_mean")

    if repo_judge is not None and _is_number(judge_mean):
        delta = _round3(float(judge_mean) - repo_judge)
        add("judge_mean_matches_repos", delta is not None and abs(delta) <= tolerance,
            f"judge_mean {judge_mean} vs per-repo mean {repo_judge} (delta {delta})")
    else:
        add("judge_mean_matches_repos", False, "cannot compare judge_mean to per-repo mean")

    if repo_objective is not None and _is_number(objective_mean):
        delta = _round3(float(objective_mean) - repo_objective)
        add("objective_mean_matches_repos", delta is not None and abs(delta) <= tolerance,
            f"objective_mean {objective_mean} vs per-repo mean {repo_objective} (delta {delta})")
    else:
        add("objective_mean_matches_repos", False, "cannot compare objective_mean to per-repo mean")


def check_aggregate_integrity(result, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Evaluate a multi-repo ``result`` against aggregate integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks, "tolerance": tolerance}

    slices = _aggregate_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no multi-repo slice with per_repo detail to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, tolerance, checks)

    return {"passed": all(c["passed"] for c in checks), "checks": checks, "tolerance": tolerance}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_aggregate_integrity` result."""
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_aggregate_integrity` result."""
    result = _dict(result)
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "aggregate integrity: no checks evaluated"
    if result.get("passed"):
        return f"aggregate integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"aggregate integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
