"""Contract tests for specs/029-benchmark-row-integrity — assert row_integrity.py
satisfies the spec's EARS criteria: constants, finite numeric semantics, slice selection,
per-slice checks, weight resolution, malformed-result robustness, logging, and pure evaluation.
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

from benchmark.row_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    DEFAULT_W_JUDGE,
    DEFAULT_W_OBJECTIVE,
    _check_rows_list,
    _is_number,
    _row_slices,
    check_row_integrity,
    failed_checks,
    integrity_headline,
)
from benchmark.score import composite_score  # noqa: E402

_MALFORMED_CHECKS = [
    42, 3.14, True, "not a list", ({"name": "x", "passed": False},), range(2),
]

ROWS = [
    {
        "winner": "challenger",
        "objective": {"module_recall": 1.0},
        "composite": composite_score("A", {"module_recall": 1.0}, 0.6, 0.4),
    },
    {
        "winner": "baseline",
        "objective": {"module_recall": 0.0},
        "composite": composite_score("B", {"module_recall": 0.0}, 0.6, 0.4),
    },
    {
        "winner": "tie",
        "objective": {"module_recall": 0.5},
        "composite": composite_score("tie", {"module_recall": 0.5}, 0.6, 0.4),
    },
]


def _artifact(rows=None, w_judge=0.6, w_objective=0.4, composite_mean=None):
    rows = copy.deepcopy(ROWS if rows is None else rows)
    dict_rows = [r for r in rows if isinstance(r, dict)]
    composites = [r["composite"] for r in dict_rows]
    judge_parts = {"challenger": 1.0, "tie": 0.5, "baseline": 0.0}
    objective_parts = [r["objective"]["module_recall"] for r in dict_rows]
    mean_composite = composite_mean
    if mean_composite is None:
        mean_composite = round(sum(composites) / len(composites), 3) if composites else 0.0
    return {
        "tasks": len(dict_rows),
        "composite_mean": mean_composite,
        "composite_parts": {
            "judge_mean": round(
                sum(judge_parts[r["winner"]] for r in dict_rows) / len(dict_rows), 3
            ),
            "objective_mean": round(sum(objective_parts) / len(dict_rows), 3),
        },
        "weights": {"judge": w_judge, "objective": w_objective},
        "rows": rows,
    }


# --- Constants ------------------------------------------------------------------------------


def test_default_tolerance_and_weight_constants():
    assert DEFAULT_TOLERANCE == 0.002
    assert DEFAULT_W_JUDGE == 0.6
    assert DEFAULT_W_OBJECTIVE == 0.4
    result = check_row_integrity(_artifact())
    assert result["tolerance"] == DEFAULT_TOLERANCE


# --- Finite numeric semantics ---------------------------------------------------------------


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)
    assert _is_number(0.6)
    assert _is_number(0)


def test_non_numeric_composite_fails_comparison():
    art = _artifact()
    art["rows"][0]["composite"] = "not a number"
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "row_composites_consistent" in failed_checks(result)


# --- Artifact shape -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_fails_artifact_shape(bad):
    result = check_row_integrity(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_artifact_shape():
    result = check_row_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


# --- Slice selection ------------------------------------------------------------------------


def test_single_repo_run_slice():
    slices = _row_slices(_artifact())
    assert slices == [("run", _artifact())]


def test_multi_repo_checks_scored_entries():
    art = {
        "per_repo": [
            _artifact(),
            {"tasks": 0, "rows": []},
            _artifact(rows=ROWS[:1]),
        ],
    }
    result = check_row_integrity(art)
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert "repo-0:composite_mean_matches_rows" in names
    assert "repo-2:row_composites_consistent" in names
    assert not any(name.startswith("repo-1:") for name in names)


def test_generalization_checks_scored_partitions():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "per_repo": [_artifact()]},
        "held_out": {"scored_repos": 1, "per_repo": [_artifact(rows=ROWS[:2])]},
    }
    result = check_row_integrity(report)
    assert result["passed"] is True
    names = [c["name"] for c in result["checks"]]
    assert "tuned:repo-0:judge_mean_matches_rows" in names
    assert "held_out:repo-0:rows_present" in names


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_row_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


# --- Weight resolution ----------------------------------------------------------------------


def test_custom_weights_are_respected():
    rows = [
        {
            "winner": "challenger",
            "objective": {"module_recall": 0.5},
            "composite": composite_score("A", {"module_recall": 0.5}, 0.8, 0.2),
        },
    ]
    art = _artifact(rows=rows, w_judge=0.8, w_objective=0.2)
    assert check_row_integrity(art)["passed"] is True


def test_default_weights_apply_when_missing():
    art = _artifact()
    del art["weights"]
    assert check_row_integrity(art)["passed"] is True


# --- Per-slice checks -----------------------------------------------------------------------


def test_consistent_single_repo_passes():
    result = check_row_integrity(_artifact())
    assert result["passed"] is True
    assert [c["name"] for c in result["checks"]] == [
        "rows_present",
        "row_composites_consistent",
        "composite_mean_matches_rows",
        "judge_mean_matches_rows",
        "objective_mean_matches_rows",
    ]


def test_row_composite_mismatch_fails():
    art = _artifact()
    art["rows"][0]["composite"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "row_composites_consistent" in failed_checks(result)


def test_composite_mean_mismatch_fails():
    art = _artifact(composite_mean=0.99)
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "composite_mean_matches_rows" in failed_checks(result)


def test_judge_mean_mismatch_fails():
    art = _artifact()
    art["composite_parts"]["judge_mean"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "judge_mean_matches_rows" in failed_checks(result)


def test_objective_mean_mismatch_fails():
    art = _artifact()
    art["composite_parts"]["objective_mean"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "objective_mean_matches_rows" in failed_checks(result)


def test_tolerance_is_configurable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_row_integrity(art, tolerance=0.002)["passed"] is True
    assert check_row_integrity(art, tolerance=0.0005)["passed"] is False


# --- Row and container robustness -----------------------------------------------------------


def test_malformed_rows_skipped_with_warning(caplog):
    art = {
        "tasks": 1,
        "composite_mean": 1.0,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": 1.0},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": [
            {
                "winner": "challenger",
                "objective": {"module_recall": 1.0},
                "composite": 1.0,
            },
            42,
        ],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        result = check_row_integrity(art)
    assert result["passed"] is True
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_malformed_per_repo_entry_skipped():
    art = {"per_repo": [42, _artifact(rows=ROWS[:1])]}
    result = check_row_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in [c["name"] for c in result["checks"]])


# --- Gate result shape ----------------------------------------------------------------------


def test_gate_returns_passed_checks_tolerance():
    result = check_row_integrity(_artifact())
    assert set(result.keys()) == {"passed", "checks", "tolerance"}
    assert all("name" in c and "passed" in c and "detail" in c for c in result["checks"])


# --- Malformed gate-result robustness -------------------------------------------------------


@pytest.mark.parametrize("bad", _MALFORMED_CHECKS)
def test_check_rows_list_treats_non_list_as_empty(bad):
    assert _check_rows_list(bad) == []


def test_check_rows_list_logs_warning_for_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list(42) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_rows_missing_keys(caplog):
    junk = [{}, {"passed": False}, {"name": "rows_present"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []
    assert failed_checks({"checks": [{"passed": False}]}) == []


# --- Integrity headline ---------------------------------------------------------------------


def test_integrity_headline_consistent_and_inconsistent():
    ok = check_row_integrity(_artifact())
    bad = _artifact()
    bad["rows"][0]["composite"] = 0.0
    assert "CONSISTENT" in integrity_headline(ok)
    assert "INCONSISTENT" in integrity_headline(check_row_integrity(bad))


def test_integrity_headline_no_checks_when_malformed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "row integrity: no checks evaluated"


def test_integrity_headline_uses_sanitized_count(caplog):
    checks = [{"name": "rows_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "row integrity: INCONSISTENT (1/1 checks failed: rows_present)"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_row_integrity_does_not_mutate_result():
    art = _artifact()
    snapshot = json.dumps(art, sort_keys=True)
    check_row_integrity(art)
    assert json.dumps(art, sort_keys=True) == snapshot
