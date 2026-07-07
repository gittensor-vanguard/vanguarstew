"""Contract tests for specs/030-benchmark-tally-integrity — assert tally_integrity.py satisfies
the spec's EARS criteria: slice selection, per-slice checks, optional-field semantics,
malformed-result robustness, headlines, and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.tally_integrity import (  # noqa: E402
    _TALLY_KEYS,
    _VALID_WINNERS,
    _check_rows_list,
    _count_row_winners,
    _dict,
    _integrity_slices,
    _is_number,
    _tally_counts,
    check_tally_integrity,
    failed_checks,
    integrity_headline,
)

_MALFORMED_CHECKS = [42, 3.14, True, "not a list", ({"name": "x", "passed": False},), range(2)]


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


def _names(result):
    return [c["name"] for c in result["checks"]]


# --- Constants ------------------------------------------------------------------------------


def test_valid_winner_labels_and_tally_keys():
    assert _VALID_WINNERS == frozenset({"challenger", "baseline", "tie"})
    assert _TALLY_KEYS == ("challenger", "baseline", "tie")


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)
    assert _tally_counts({"challenger": True, "baseline": 0, "tie": 0}) is None


# --- Input coercion -------------------------------------------------------------------------


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Tally counts ---------------------------------------------------------------------------


def test_tally_counts_happy_path():
    assert _tally_counts({"challenger": 2, "baseline": 1, "tie": 0}) == {
        "challenger": 2,
        "baseline": 1,
        "tie": 0,
    }


def test_tally_counts_rejects_malformed():
    assert _tally_counts({"challenger": 1, "baseline": "x", "tie": 0}) is None
    assert _tally_counts("not a dict") is None


# --- Row winner recount ---------------------------------------------------------------------


def test_count_row_winners_ignores_unknown_labels():
    rows = [{"winner": "challenger"}, {"winner": "unknown"}, {"winner": "tie"}]
    assert _count_row_winners(rows) == {"challenger": 1, "baseline": 0, "tie": 1}


def test_count_row_winners_none_when_rows_none():
    assert _count_row_winners(None) is None


# --- Slice selection ------------------------------------------------------------------------


def test_integrity_slices_single_run():
    art = _artifact(tasks=2, challenger=1, baseline=1, tie=0)
    assert _integrity_slices(art) == [("run", art)]


def test_integrity_slices_multi_repo():
    art = {
        "per_repo": [
            _artifact(tasks=2, challenger=1, baseline=1, tie=0),
            {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}},
        ],
    }
    slices = _integrity_slices(art)
    assert len(slices) == 1
    assert slices[0][0] == "repo-0"


def test_integrity_slices_generalization():
    part = {
        "scored_repos": 1,
        "rows": _rows(1, 0, 0),
        "tasks": 1,
        "tally": {"challenger": 1, "baseline": 0, "tie": 0},
    }
    slices = _integrity_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned", part) in slices
    assert ("held_out", part) in slices


def test_integrity_slices_empty_when_no_scored_slice():
    assert _integrity_slices({}) == []
    assert _integrity_slices({"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}}) == []


# --- Per-slice checks -----------------------------------------------------------------------


def test_consistent_single_slice_passes_all_checks():
    result = check_tally_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "tally_present",
        "tasks_reported",
        "tally_sums_to_tasks",
        "rows_match_tasks",
        "row_winners_match_tally",
        "decisive_margin_matches",
    ]


def test_optional_rows_and_margin_checks_skipped():
    entry = {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 1, "tie": 0},
        "decisive_margin": 1,
    }
    without_rows = check_tally_integrity({"per_repo": [entry]})
    assert without_rows["passed"] is True
    assert "rows_match_tasks" not in _names(without_rows)

    without_margin = check_tally_integrity(_artifact(margin=False))
    assert without_margin["passed"] is True
    assert "decisive_margin_matches" not in _names(without_margin)


def test_tally_sum_mismatch_fails():
    art = _artifact()
    art["tally"]["challenger"] = 99
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_row_count_mismatch_fails():
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


def test_decisive_margin_mismatch_fails():
    result = check_tally_integrity(_artifact(margin=99))
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


# --- Gate entrypoint ------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_fails_artifact_shape(bad):
    result = check_tally_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_artifact_shape():
    result = check_tally_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_every_check_row_has_required_keys():
    result = check_tally_integrity(_artifact())
    assert all({"name", "passed", "detail"} <= frozenset(c) for c in result["checks"])


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_skips_non_dict_rows(caplog):
    mixed = [42, {"name": "tally_present", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        rows = _check_rows_list(mixed)
    assert rows == [{"name": "tally_present", "passed": True}]
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks("not a dict") == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert failed_checks({"checks": checks}) == ["tally_present"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


# --- Integrity headline ---------------------------------------------------------------------


def test_integrity_headline_consistent_and_inconsistent():
    assert integrity_headline(check_tally_integrity(_artifact())) == (
        "tally integrity: CONSISTENT (6 checks passed)"
    )
    art = _artifact()
    art["tally"]["challenger"] = 99
    line = integrity_headline(check_tally_integrity(art))
    assert line.startswith("tally integrity: INCONSISTENT (")
    assert "tally_sums_to_tasks" in line


def test_integrity_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "tally integrity: no checks evaluated"


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "tally integrity: INCONSISTENT (1/1 checks failed: tally_present)"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_tally_integrity_does_not_mutate_result():
    art = _artifact()
    snapshot = copy.deepcopy(art)
    check_tally_integrity(art)
    assert art == snapshot
