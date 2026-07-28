"""One fail-closed integrity gate for artifacts used by live PR decisions.

The individual integrity modules remain useful diagnostics.  This module composes the checks that
must all pass before a baseline/candidate pair may be scored or sent to an attested validator.
It intentionally returns check names only: raw rows, repository identities, and hidden-target
details stay in the private artifacts.
"""

from __future__ import annotations

from benchmark.aggregate_integrity import check_aggregate_integrity
from benchmark.judge_report_integrity import check_judge_report_integrity
from benchmark.objective_integrity import check_objective_integrity
from benchmark.row_integrity import check_row_integrity
from benchmark.score_integrity import check_score_integrity
from benchmark.tally_integrity import check_tally_integrity
from benchmark.weight_integrity import check_weight_integrity

LIVE_ARTIFACT_KEYS = (
    "baseline_public",
    "candidate_public",
    "baseline_private",
    "candidate_private",
)

_CHECKERS = (
    ("tally", check_tally_integrity),
    ("rows", check_row_integrity),
    ("score", check_score_integrity),
    ("weights", check_weight_integrity),
    ("judge_report", check_judge_report_integrity),
    ("objective", check_objective_integrity),
)


def _failed_names(result) -> list[str]:
    if not isinstance(result, dict) or not isinstance(result.get("checks"), list):
        return ["malformed_result"]
    names = []
    for row in result["checks"]:
        if not isinstance(row, dict) or row.get("passed") is not True:
            name = row.get("name") if isinstance(row, dict) else None
            names.append(name if isinstance(name, str) and name else "malformed_check")
    return names


def _scored_slices(artifact: dict) -> list[dict]:
    if isinstance(artifact.get("tuned"), dict) or isinstance(artifact.get("held_out"), dict):
        return [
            value for key in ("tuned", "held_out")
            if isinstance((value := artifact.get(key)), dict)
        ]
    return [artifact]


def _sample_adequacy(artifact: dict, min_tasks_per_repo: int) -> dict:
    failures = []
    for slice_index, slice_ in enumerate(_scored_slices(artifact)):
        per_repo = slice_.get("per_repo")
        repos = per_repo if isinstance(per_repo, list) else [slice_]
        scored = 0
        for repo_index, repo in enumerate(repos):
            if not isinstance(repo, dict) or repo.get("error"):
                continue
            tasks = repo.get("tasks")
            if isinstance(tasks, bool) or not isinstance(tasks, int) or tasks < min_tasks_per_repo:
                failures.append(f"slice{slice_index}:repo{repo_index}:minimum_tasks")
            else:
                scored += 1
        if scored == 0:
            failures.append(f"slice{slice_index}:scored_repos")
    return {"passed": not failures, "failed_checks": failures}


def check_live_artifact(artifact, *, min_tasks_per_repo: int = 3) -> dict:
    """Run every required consistency check for one private live artifact."""
    if not isinstance(artifact, dict):
        return {
            "passed": False,
            "gates": {"shape": {"passed": False, "failed_checks": ["artifact_object"]}},
        }
    gates = {}
    for name, checker in _CHECKERS:
        result = checker(artifact)
        gates[name] = {
            "passed": result.get("passed") is True,
            "failed_checks": _failed_names(result),
        }
    if any(isinstance(slice_.get("per_repo"), list) for slice_ in _scored_slices(artifact)):
        result = check_aggregate_integrity(artifact)
        gates["aggregate"] = {
            "passed": result.get("passed") is True,
            "failed_checks": _failed_names(result),
        }
    gates["sample_adequacy"] = _sample_adequacy(artifact, min_tasks_per_repo)
    return {"passed": all(gate["passed"] is True for gate in gates.values()), "gates": gates}


def check_live_artifacts(artifacts, *, min_tasks_per_repo: int = 3) -> dict:
    """Check the exact four artifacts required by the dual-target decision."""
    if not isinstance(artifacts, dict) or set(artifacts) != set(LIVE_ARTIFACT_KEYS):
        return {
            "passed": False,
            "artifacts": {},
            "failed_artifacts": list(LIVE_ARTIFACT_KEYS),
        }
    results = {
        key: check_live_artifact(artifacts[key], min_tasks_per_repo=min_tasks_per_repo)
        for key in LIVE_ARTIFACT_KEYS
    }
    failed = [key for key, result in results.items() if result["passed"] is not True]
    return {"passed": not failed, "artifacts": results, "failed_artifacts": failed}
