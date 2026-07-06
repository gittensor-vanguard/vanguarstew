"""Contract tests for specs/030-benchmark-tally-integrity — assert tally_integrity.py
satisfies the spec's EARS criteria: winner vocabulary, finite numeric semantics, slice selection,
per-slice checks, container robustness, malformed-result robustness, logging, and pure evaluation.
Offline, deterministic.
"""

import copy
import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.tally_integrity import (  # noqa: E402
    _VALID_WINNERS,
    _check_rows_list,
    _count_row_winners,
    _integrity_slices,
    _is_number,
    _tally_counts,
    check_tally_integrity,
    failed_checks,
    integrity_headline,
)

_MALFORMED_CHECKS = [
    42, 3.14, True, "not a list", ({"name": "x", "passed": False},), range(2),
]


def _rows(challenger=2, baseline=1, tie=0):
    return (
        [{"winner": "challenger"}] * challenger
        + [{"winner": "baseline"}] * baseline
        + [{"winner": "tie"}] * tie
    )


def _slice(tasks=3, challenger=2, baseline=1, tie=0, margin=None, rows=None):
    tally = {"challenger": challenger, "baseline": baseline, "tie": tie}
    if rows is None:
        rows = _rows(challenger, baseline, tie)
    art = {"tasks": tasks, "tally": tally, "rows": rows}
    if margin is not False:
        art["decisive_margin"] = margin if margin is not None else challenger - baseline
    return art


def _artifact(**kwargs):
    return copy.deepcopy(_slice(**kwargs))


# --- Winner vocabulary ----------------------------------------------------------------------


def test_valid_winners_constant():
    assert _VALID_WINNERS == frozenset({"challenger", "baseline", "tie"})


def test_count_row_winners_ignores_unknown_labels():
    rows = [{"winner": "challenger"}, {"winner": "unknown"}, {"winner": "tie"}]
    assert _count_row_winners(rows) == {"challenger": 1, "baseline": 0, "tie": 1}


# --- Finite numeric semantics ---------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)
    assert _is_number(3)
    assert _is_number(0.0)


def test_tally_counts_rejects_non_numeric():
    assert _tally_counts({"challenger": 1, "baseline": "x", "tie": 0}) is None
    assert _tally_counts("not a dict") is None
    assert _tally_counts({"challenger": True, "baseline": 0, "tie": 0}) is None


# --- Artifact shape -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_fails_artifact_shape(bad):
    result = check_tally_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_artifact_shape():
    result = check_tally_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_zero_tasks_not_selected():
    result = check_tally_integrity(
        {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}}
    )
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


# --- Slice selection ------------------------------------------------------------------------


def test_single_repo_run_slice():
    art = _artifact()
    slices = _integrity_slices(art)
    assert ("run", art) in slices


def test_multi_repo_checks_scored_entries():
    art = {
        "per_repo": [
            _artifact(tasks=2, challenger=1, baseline=1, tie=0),
            {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}},
            _artifact(tasks=1, challenger=1, baseline=0, tie=0),
        ],
    }
    result = check_tally_integrity(art)
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert "repo-0:row_winners_match_tally" in names
    assert "repo-2:decisive_margin_matches" in names
    assert not any(name.startswith("repo-1:") for name in names)


def test_generalization_checks_scored_partitions():
    report = {
        "generalization_gap": 0.1,
        "tuned": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=2, challenger=2, baseline=0, tie=0)],
        },
        "held_out": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=1, challenger=0, baseline=1, tie=0)],
        },
    }
    result = check_tally_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:tally_sums_to_tasks" in [c["name"] for c in result["checks"]]


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


# --- Per-slice checks -----------------------------------------------------------------------


def test_consistent_single_repo_passes():
    result = check_tally_integrity(_artifact())
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "tally_present",
        "tasks_reported",
        "tally_sums_to_tasks",
        "rows_match_tasks",
        "row_winners_match_tally",
        "decisive_margin_matches",
    ]


def test_tally_sum_mismatch_fails():
    art = _artifact()
    art["tally"]["challenger"] = 99
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_rows_match_tasks_when_rows_present():
    art = _artifact()
    art["rows"] = art["rows"][:-1]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "rows_match_tasks" in failed_checks(result)


def test_row_winners_mismatch_fails():
    art = _artifact()
    art["rows"][0]["winner"] = "baseline"
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "row_winners_match_tally" in failed_checks(result)


def test_decisive_margin_matches_when_present():
    art = _artifact(margin=99)
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


def test_slice_without_rows_skips_row_checks():
    entry = {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 1, "tie": 0},
        "decisive_margin": 1,
    }
    result = check_tally_integrity({"per_repo": [entry]})
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert "rows_match_tasks" not in names
    assert "row_winners_match_tally" not in names


def test_slice_without_margin_skips_margin_check():
    art = _artifact(margin=False)
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "decisive_margin_matches" not in [c["name"] for c in result["checks"]]


# --- Tally and container robustness ---------------------------------------------------------


def test_malformed_rows_skipped_with_warning(caplog):
    art = {
        "tasks": 2,
        "tally": {"challenger": 2, "baseline": 0, "tie": 0},
        "decisive_margin": 2,
        "rows": [{"winner": "challenger"}, 42],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "rows_match_tasks" in failed_checks(result)
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_malformed_per_repo_entry_skipped():
    art = {"per_repo": [42, _artifact(tasks=1, challenger=1, baseline=0, tie=0)]}
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in [c["name"] for c in result["checks"]])


# --- Gate result shape ----------------------------------------------------------------------


def test_gate_returns_passed_and_checks():
    result = check_tally_integrity(_artifact())
    assert set(result.keys()) == {"passed", "checks"}
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_logs_warning_for_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert _check_rows_list(42) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks("not a dict") == []


# --- Integrity headline ---------------------------------------------------------------------


def test_integrity_headline_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_tally_integrity(_artifact()))
    art = _artifact()
    art["tally"]["challenger"] = 99
    assert "INCONSISTENT" in integrity_headline(check_tally_integrity(art))


def test_integrity_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "tally integrity: no checks evaluated"


def test_integrity_headline_uses_sanitized_count(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "tally integrity: INCONSISTENT (1/1 checks failed: tally_present)"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_tally_integrity_does_not_mutate_result():
    art = _artifact()
    snapshot = json.dumps(art, sort_keys=True)
    check_tally_integrity(art)
    assert json.dumps(art, sort_keys=True) == snapshot
