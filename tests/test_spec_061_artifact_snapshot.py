"""Contract tests for specs/061-benchmark-artifact-snapshot — assert artifact_snapshot.py
satisfies the spec's EARS criteria: task/repo tallies, error flags, decisive margin,
headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.artifact_snapshot import (  # noqa: E402
    _decisive_margin,
    _dict,
    _has_error,
    _is_int,
    _is_number,
    _per_repo_tasks,
    _repo_tally,
    _task_total,
    snapshot,
    snapshot_headline,
)

_REQUIRED_KEYS = frozenset({
    "kind",
    "headline_score",
    "scored",
    "tasks",
    "repos",
    "generalization_gap",
    "repo_set",
    "decisive_margin",
    "offline",
    "has_error",
})


def _repo(name, tasks=5, score=0.6, error=None):
    row = {"repo": name, "tasks": tasks, "composite_mean": score}
    if error:
        row["error"] = error
    return row


def _multi(*repos, scored=None):
    scored = scored if scored is not None else len(repos)
    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": len(repos) - scored,
        "composite_mean": 0.65,
        "decisive_margin": 2,
        "offline": True,
        "per_repo": [_repo(r) for r in repos],
    }


def _single(score=0.7, tasks=8):
    return {
        "composite_mean": score,
        "tasks": tasks,
        "decisive_margin": 1,
        "offline": False,
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced(bad):
    out = snapshot(bad)
    assert out["kind"] == "invalid"
    assert out["headline_score"] is None
    assert out["scored"] is False
    assert out["has_error"] is False


def test_dict_and_is_int_helpers():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _is_int(0) and _is_int(2)
    assert not _is_int(True)
    assert not _is_int(1.0)


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool_and_non_finite():
    assert _is_number(0.6)
    assert _is_number(1)
    assert not _is_number(True)
    assert not _is_number("0.6")
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


# --- Task total -----------------------------------------------------------------------------


def test_task_total_top_level_and_per_repo():
    assert _task_total(_single(tasks=8)) == 8
    assert _task_total(_multi("a", "b")) == 10
    assert _per_repo_tasks(None) is None
    assert _per_repo_tasks("bad") is None
    assert _per_repo_tasks([]) == 0


def test_task_total_skips_malformed_and_non_finite():
    assert _task_total({"composite_mean": 0.5, "tasks": float("nan")}) is None
    art = {
        "per_repo": ["oops", {"repo": "a", "tasks": float("inf")}, _repo("b", tasks=4)],
        "composite_mean": 0.5,
    }
    assert _task_total(art) == 4


def test_task_total_generalization_sums_partitions():
    art = {
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [_repo("t1", tasks=3)]},
        "held_out": {"per_repo": [_repo("h1", tasks=2)]},
    }
    assert _task_total(art) == 5


# --- Repo tally -----------------------------------------------------------------------------


def test_repo_tally_happy_path_and_incoherent():
    assert _repo_tally(_multi("a", "b")) == {"total": 2, "scored": 2, "skipped": 0}
    bad = _multi("a", "b")
    bad["skipped"] = 99
    assert _repo_tally(bad) is None
    assert _repo_tally({"repos": 0, "scored_repos": 0}) is None
    assert _repo_tally({"repos": True, "scored_repos": 1}) is None


# --- Error flag -----------------------------------------------------------------------------


def test_has_error_top_level_and_per_repo():
    assert _has_error({"error": "clone failed"}) is True
    art = _multi("ok")
    art["per_repo"].append(_repo("bad", error="freeze failed"))
    assert _has_error(art) is True
    assert _has_error(_multi("ok")) is False


def test_has_error_string_rows_and_falsy():
    art = _multi("ok")
    art["per_repo"].append("corrupt row")
    assert _has_error(art) is True
    blank = _multi("ok")
    blank["per_repo"].append("   ")
    assert _has_error(blank) is False
    for falsy in (0, False, None, ""):
        row = _multi("ok")
        row["per_repo"].append({"repo": "x", "tasks": 0, "error": falsy})
        assert _has_error(row) is False, falsy


# --- Decisive margin ------------------------------------------------------------------------


def test_decisive_margin_top_level_and_judge_report():
    assert _decisive_margin(_single(), "single") == 1
    art = {
        "generalization_gap": 0.0,
        "tuned": {"judge_report": {"wins": 5, "losses": 2}},
        "held_out": {},
    }
    assert _decisive_margin(art, "generalization") == 3
    assert _decisive_margin({"decisive_margin": float("nan")}, "single") is None


# --- Snapshot -------------------------------------------------------------------------------


def test_single_multi_generalization_shapes():
    single = snapshot(_single())
    assert single["kind"] == "single"
    assert single["headline_score"] == 0.7
    assert single["scored"] is True
    assert single["tasks"] == 8
    assert single["repos"] is None
    assert single["offline"] is False

    multi = snapshot(_multi("a", "b", "c"))
    assert multi["kind"] == "multi"
    assert multi["repos"] == {"total": 3, "scored": 3, "skipped": 0}
    assert multi["decisive_margin"] == 2

    gen = snapshot({
        "repo_set": "example.json",
        "tuned": _multi("t1", "t2"),
        "held_out": _multi("h1"),
        "generalization_gap": 0.08,
    })
    assert gen["kind"] == "generalization"
    assert gen["generalization_gap"] == 0.08
    assert gen["repo_set"] == "example.json"
    assert gen["repos"] == {"total": 2, "scored": 2, "skipped": 0}


def test_summary_always_includes_required_keys():
    for artifact in (_single(), _multi("a"), {"error": "x"}, None, {}):
        out = snapshot(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Snapshot headline ----------------------------------------------------------------------


def test_headline_exact_format():
    out = snapshot(_single())
    assert snapshot_headline(out) == "snapshot: single headline=0.700 tasks=8 status=ok"


def test_headline_n_a_and_error_status():
    out = snapshot({"error": "clone failed", "tasks": 0})
    assert snapshot_headline(out) == "snapshot: single headline=n/a tasks=0 status=error"
    assert snapshot_headline({}) == "snapshot: unknown headline=n/a tasks=n/a status=ok"
    assert snapshot_headline("nope") == "snapshot: unknown headline=n/a tasks=n/a status=ok"


# --- Pure evaluation ------------------------------------------------------------------------


def test_snapshot_does_not_mutate_artifact():
    art = _multi("a", "b")
    snapshot_copy = copy.deepcopy(art)
    snapshot(art)
    assert art == snapshot_copy
