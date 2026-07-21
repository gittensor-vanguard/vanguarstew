"""Spec 065 contract tests for benchmark/artifact_snapshot.py (replay artifact snapshot).

Pins the as-built behavior described in specs/065-benchmark-artifact-snapshot/spec.md with literal
expected values. Broader coverage lives in tests/test_artifact_snapshot.py.
"""

import copy
import logging
import os
import sys

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

# A minimal single-repo artifact that scores (headline_score reads composite_mean).
_SINGLE = {"composite_mean": 0.6, "tasks": 4}
# A multi-repo artifact: per_repo present, top-level composite_mean.
_MULTI = {"composite_mean": 0.5, "repos": 2, "scored_repos": 2,
          "per_repo": [{"tasks": 3, "composite_mean": 0.4}, {"tasks": 2, "composite_mean": 0.6}]}
# A generalization artifact: tuned/held_out + generalization_gap.
_GEN = {"generalization_gap": 0.1, "repo_set": "curated.json",
        "tuned": {"composite_mean": 0.6, "repos": 2, "scored_repos": 2,
                  "per_repo": [{"tasks": 3}, {"tasks": 2}]},
        "held_out": {"composite_mean": 0.5, "per_repo": [{"tasks": 4}]}}


# --- Numeric helpers -----------------------------------------------------------------------------

def test_is_number_semantics():
    assert _is_number(0.6) is True
    assert _is_number(3) is True
    assert _is_number(True) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number("3") is False
    assert _is_number(None) is False


def test_is_number_rejects_oversized_int():
    assert _is_number(10 ** 400) is False


def test_is_int_semantics():
    assert _is_int(3) is True
    assert _is_int(True) is False
    assert _is_int(3.0) is False


def test_dict_helper():
    d = {"a": 1}
    assert _dict(d) is d
    for bad in (None, 5, "x", [1]):
        assert _dict(bad) == {}


# --- Task counting -------------------------------------------------------------------------------

def test_per_repo_tasks_none_and_non_list(caplog):
    assert _per_repo_tasks(None) is None
    with caplog.at_level(logging.WARNING, logger="benchmark.artifact_snapshot"):
        assert _per_repo_tasks(42) is None
    assert any("not a list" in r.message for r in caplog.records)


def test_per_repo_tasks_sums_and_skips(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.artifact_snapshot"):
        total = _per_repo_tasks([{"tasks": 3}, "oops", {"tasks": 2}, {"tasks": "x"}])
    assert total == 5                                   # 3 + 2; "oops" and non-numeric skipped
    assert any("not an object" in r.message for r in caplog.records)
    assert _per_repo_tasks([]) == 0                     # empty list -> 0, not None
    assert _per_repo_tasks([{"repo": "a"}]) == 0        # no numeric tasks seen -> 0


def test_task_total_prefers_top_level():
    assert _task_total({"tasks": 7, "per_repo": [{"tasks": 100}]}) == 7


def test_task_total_generalization_sums_partitions():
    assert _task_total(_GEN) == 9                       # tuned 3+2, held_out 4
    both_absent = {"generalization_gap": 0.0, "tuned": {}, "held_out": {}}
    assert _task_total(both_absent) is None


def test_task_total_multi_uses_per_repo():
    assert _task_total(_MULTI) == 5


# --- Repo tally ----------------------------------------------------------------------------------

def test_repo_tally_requires_coherent_counts():
    assert _repo_tally({"repos": 3, "scored_repos": 2}) == {"total": 3, "scored": 2, "skipped": 1}
    assert _repo_tally({"repos": 0, "scored_repos": 0}) is None       # repos must be > 0
    assert _repo_tally({"repos": 2, "scored_repos": 3}) is None       # scored > repos
    assert _repo_tally({"repos": 2, "scored_repos": -1}) is None
    assert _repo_tally({"repos": 2}) is None                          # scored_repos missing
    assert _repo_tally({"repos": True, "scored_repos": 1}) is None    # bool is not an int here


def test_repo_tally_rejects_inconsistent_skipped():
    assert _repo_tally({"repos": 3, "scored_repos": 2, "skipped": 1}) == {
        "total": 3, "scored": 2, "skipped": 1}
    assert _repo_tally({"repos": 3, "scored_repos": 2, "skipped": 0}) is None   # != repos - scored


def test_repo_tally_shape():
    assert set(_repo_tally({"repos": 2, "scored_repos": 2})) == {"total", "scored", "skipped"}


# --- Error detection -----------------------------------------------------------------------------

def test_has_error_top_level():
    assert _has_error({"error": "boom"}) is True
    assert _has_error({"error": ""}) is False


def test_has_error_generalization_partition():
    art = copy.deepcopy(_GEN)
    art["tuned"]["per_repo"] = [{"tasks": 3, "error": "clone failed"}]
    assert _has_error(art) is True


def test_has_error_multi_per_repo():
    art = {"composite_mean": 0.5, "repos": 2, "scored_repos": 1,
           "per_repo": [{"tasks": 3, "composite_mean": 0.4}, {"error": "skip"}]}
    assert _has_error(art) is True


def test_single_repo_no_error():
    assert _has_error(_SINGLE) is False


# --- Decisive margin -----------------------------------------------------------------------------

def test_decisive_margin_top_level():
    assert _decisive_margin({"decisive_margin": 4}, "single") == 4


def test_decisive_margin_from_judge_report():
    art = {"judge_report": {"wins": 6, "losses": 2}}
    assert _decisive_margin(art, "multi") == 4


def test_decisive_margin_generalization_uses_tuned():
    art = {"tuned": {"judge_report": {"wins": 5, "losses": 1}}}
    assert _decisive_margin(art, "generalization") == 4


def test_decisive_margin_none_when_unavailable():
    assert _decisive_margin({"judge_report": {"wins": 5}}, "multi") is None
    assert _decisive_margin({"decisive_margin": float("nan")}, "single") is None


# --- Snapshot body -------------------------------------------------------------------------------

_KEYS = {"kind", "headline_score", "scored", "tasks", "repos", "generalization_gap",
         "repo_set", "decisive_margin", "offline", "has_error"}


def test_snapshot_keys_are_fixed():
    for art in (_SINGLE, _MULTI, _GEN, {}, "not-a-dict"):
        assert set(snapshot(art)) == _KEYS


def test_snapshot_coerces_non_dict():
    body = snapshot("not-a-dict")
    assert body["headline_score"] is None and body["scored"] is False


def test_snapshot_masks_wrong_typed_fields():
    art = {"composite_mean": 0.6, "tasks": 4, "generalization_gap": "0.1",
           "repo_set": 123, "offline": "yes"}
    body = snapshot(art)
    assert body["generalization_gap"] is None      # not a number
    assert body["repo_set"] is None                # not a str
    assert body["offline"] is None                 # not a bool
    # a well-typed set survives
    good = snapshot({"composite_mean": 0.6, "tasks": 4, "offline": True, "repo_set": "curated"})
    assert good["offline"] is True and good["repo_set"] == "curated"


def test_snapshot_repos_generalization_and_multi():
    assert snapshot(_MULTI)["repos"] == {"total": 2, "scored": 2, "skipped": 0}
    assert snapshot(_GEN)["repos"] == {"total": 2, "scored": 2, "skipped": 0}   # tuned tally
    assert snapshot(_SINGLE)["repos"] is None


# --- Headline ------------------------------------------------------------------------------------

def test_headline_format():
    line = snapshot_headline(snapshot(_SINGLE))
    assert line == "snapshot: single headline=0.600 tasks=4 status=ok"
    err = snapshot_headline({"kind": "multi", "headline_score": 0.5, "tasks": 5, "has_error": True})
    assert err == "snapshot: multi headline=0.500 tasks=5 status=error"


def test_headline_masks_non_numeric_and_non_dict():
    line = snapshot_headline({"kind": None, "headline_score": None, "tasks": None})
    assert line == "snapshot: unknown headline=n/a tasks=n/a status=ok"
    assert snapshot_headline("nope") == "snapshot: unknown headline=n/a tasks=n/a status=ok"


# --- Pure evaluation -----------------------------------------------------------------------------

def test_snapshot_does_not_mutate_artifact():
    art = copy.deepcopy(_GEN)
    snapshot(art)
    assert art == _GEN
