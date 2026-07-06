"""Contract tests for specs/018-benchmark-score-calibration — assert score_calibration.py
satisfies the spec's EARS criteria: scenario validation, corpus loading, numeric matching
(including legitimate 0.0 and non-finite actuals), aggregation, and malformed-result
robustness. Offline, deterministic.
"""

import json
import logging
import math
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_calibration import (  # noqa: E402
    _failed_ids_list,
    _values_match,
    calibration_headline,
    check_calibration,
    failed_scenarios,
    load_corpus,
    load_manifest,
    load_scenario,
    run_scenario,
    validate_scenario,
)

_VALID = {
    "id": "sample",
    "description": "sample scenario",
    "plan": [{"title": "fix loader", "kind": "bugfix", "files": ["core/loader.py"]}],
    "revealed": [{"subject": "fix: race in loader", "files": ["core/loader.py"]}],
    "expected": {"module_recall": 1.0, "objective_component": 1.0},
}

_MALFORMED_CONTAINERS = [42, 3.14, True, {"id": "x"}, "not a list"]


# --- Scenario validation ------------------------------------------------------------------


def test_validate_scenario_empty_errors_for_well_formed():
    assert validate_scenario(_VALID) == []


def test_validate_scenario_rejects_non_dict():
    assert validate_scenario([])[0] == "scenario: must be a JSON object"


def test_validate_scenario_reports_missing_required_keys():
    errors = validate_scenario({"id": "x"})
    assert any("missing required keys" in err for err in errors)


def test_validate_scenario_rejects_empty_expected():
    bad = dict(_VALID, expected={})
    assert any("expected must be a non-empty object" in err for err in validate_scenario(bad))


def test_validate_scenario_rejects_non_list_plan():
    bad = dict(_VALID, plan="not a list")
    assert any("plan must be a list" in err for err in validate_scenario(bad))


def test_validate_scenario_rejects_non_list_revealed():
    bad = dict(_VALID, revealed=42)
    assert any("revealed must be a list" in err for err in validate_scenario(bad))


def test_validate_scenario_rejects_bad_winner():
    bad = dict(_VALID, winner="Z", expected={"module_recall": 0.5})
    assert any("winner must be one of" in err for err in validate_scenario(bad))


# --- Manifest and corpus loading ----------------------------------------------------------


def test_load_manifest_rejects_non_object():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "manifest.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)
        with pytest.raises(ValueError, match="JSON object"):
            load_manifest(Path(path))


def test_load_manifest_and_corpus_are_consistent():
    manifest = load_manifest()
    corpus = load_corpus()
    assert len(manifest["scenarios"]) == len(corpus)
    assert {s["id"] for s in corpus} == {entry["id"] for entry in manifest["scenarios"]}


def test_load_scenario_raises_on_validation_errors():
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump({}, f)
        path = f.name
    try:
        with pytest.raises(ValueError, match="missing required keys"):
            load_scenario(Path(path))
    finally:
        os.unlink(path)


def test_load_corpus_rejects_duplicate_ids():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "corpus")
        scenarios = os.path.join(root, "scenarios")
        os.makedirs(scenarios)
        manifest = {
            "scenarios": [
                {"id": "dup", "file": "a.json"},
                {"id": "dup", "file": "b.json"},
            ],
        }
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f)
        for name in ("a.json", "b.json"):
            with open(os.path.join(scenarios, name), "w", encoding="utf-8") as f:
                json.dump(dict(_VALID, id="dup"), f)
        with pytest.raises(ValueError, match="duplicate"):
            load_corpus(root)


# --- Scenario replay ----------------------------------------------------------------------


def test_run_scenario_reports_pass_and_required_fields():
    row = run_scenario(_VALID)
    assert row["passed"] is True
    for key in ("id", "description", "expected", "actual", "detail"):
        assert key in row
    assert row["actual"]["module_recall"] == 1.0


def test_run_scenario_reports_fail_on_mismatch():
    row = run_scenario(dict(_VALID, expected={"module_recall": 0.0}))
    assert row["passed"] is False
    assert "module_recall" in row["detail"]


def test_run_scenario_includes_composite_when_winner_set():
    scenario = dict(
        _VALID,
        winner="A",
        expected={"objective_component": 1.0, "composite_score": 1.0},
    )
    row = run_scenario(scenario)
    assert row["passed"] is True
    assert "composite_score" in row["actual"]


# --- Numeric matching ---------------------------------------------------------------------


def test_legitimate_zero_score_passes_when_actual_is_zero():
    """0.0 is a real measurement, not a missing placeholder."""
    scenario = {
        "id": "zero-hit",
        "description": "no overlap",
        "plan": [{"title": "unrelated", "kind": "feature", "files": ["other.py"]}],
        "revealed": [{"subject": "fix: loader", "files": ["core/loader.py"]}],
        "expected": {"module_recall": 0.0},
    }
    row = run_scenario(scenario)
    assert row["passed"] is True
    assert row["actual"]["module_recall"] == 0.0


def test_numeric_match_none_actual_fails_against_zero_expected():
    assert not _values_match(0.0, None, 0.001)


def test_numeric_match_non_finite_actual_fails():
    for bad in (math.nan, math.inf, -math.inf):
        assert not _values_match(0.5, bad, 0.001)
        assert not _values_match(0.0, bad, 0.001)


def test_numeric_match_bool_uses_identity():
    assert _values_match(True, True, 0.001)
    assert not _values_match(True, 1, 0.001)


def test_tolerance_is_configurable():
    scenario = dict(_VALID, expected={"module_recall": 0.999})
    assert run_scenario(scenario, tolerance=0.01)["passed"] is True
    assert run_scenario(scenario, tolerance=0.0001)["passed"] is False


def test_check_calibration_passes_tolerance_to_each_scenario():
    scenario = dict(_VALID, expected={"module_recall": 0.999})
    loose = check_calibration([scenario], tolerance=0.01)
    tight = check_calibration([scenario], tolerance=0.0001)
    assert loose["passed"] is True
    assert tight["passed"] is False
    assert loose["tolerance"] == 0.01


# --- Calibration aggregation --------------------------------------------------------------


def test_check_calibration_passes_single_valid_scenario():
    result = check_calibration([_VALID])
    assert result["passed"] is True
    assert result["scenario_count"] == 1
    assert result["failed"] == []


def test_check_calibration_fails_when_field_mismatch():
    result = check_calibration([dict(_VALID, expected={"module_recall": 0.0})])
    assert result["passed"] is False
    assert result["failed"] == ["sample"]


def test_check_calibration_does_not_mutate_corpus():
    corpus = [dict(_VALID)]
    before = json.dumps(corpus, sort_keys=True)
    check_calibration(corpus)
    assert json.dumps(corpus, sort_keys=True) == before


# --- Malformed calibration-result robustness ----------------------------------------------


def test_failed_scenarios_returns_empty_for_non_dict():
    assert failed_scenarios(None) == []
    assert failed_scenarios(42) == []


@pytest.mark.parametrize("bad", _MALFORMED_CONTAINERS)
def test_failed_ids_list_treats_non_list_as_empty(bad):
    assert _failed_ids_list(bad) == []


def test_failed_ids_list_skips_blank_entries():
    assert failed_scenarios({"failed": ["a", 42, ""]}) == ["a"]


def test_failed_ids_list_logs_when_failed_is_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_calibration"):
        assert _failed_ids_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


# --- Calibration headline -----------------------------------------------------------------


def test_calibration_headline_no_scenarios_for_non_dict():
    assert calibration_headline(None) == "score calibration: no scenarios evaluated"
    assert calibration_headline({}) == "score calibration: no scenarios evaluated"


def test_calibration_headline_pass_includes_count():
    good = check_calibration([_VALID])
    headline = calibration_headline(good)
    assert "PASS" in headline
    assert "score calibration:" in headline


def test_calibration_headline_fail_lists_failed_ids():
    bad = check_calibration([dict(_VALID, expected={"module_recall": 0.0})])
    headline = calibration_headline(bad)
    assert "FAIL" in headline
    assert "sample" in headline


def test_calibration_headline_survives_malformed_failed_field():
    assert "FAIL" in calibration_headline(
        {"passed": False, "scenario_count": 2, "failed": 42},
    )


# --- Shipped corpus sanity (offline gate) -------------------------------------------------


def test_shipped_corpus_passes_calibration():
    result = check_calibration()
    assert result["passed"] is True
    assert result["scenario_count"] >= 1
    assert failed_scenarios(result) == []
