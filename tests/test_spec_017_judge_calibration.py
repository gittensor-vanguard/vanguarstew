"""Contract tests for specs/017-benchmark-judge-calibration — assert judge_calibration.py
satisfies the spec's EARS criteria: scenario validation, corpus loading, calibration
aggregation, symmetry checks, and malformed-result robustness. Offline, deterministic.
"""

import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.judge_calibration import (  # noqa: E402
    _failed_ids_list,
    _symmetry_checks_list,
    calibration_headline,
    check_calibration,
    check_symmetry,
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
    "context": {"frozen_at": {"commit": "abc"}},
    "revealed": {"commits": []},
    "submission_a": {
        "philosophy": {"summary": "a"},
        "plan": [{"title": "fix"}],
        "rationale": "x",
    },
    "submission_b": {"philosophy": {}, "plan": [], "rationale": ""},
    "expected_winner": "A",
}

_MALFORMED_CONTAINERS = [42, 3.14, True, {"id": "x"}, "not a list"]


# --- Scenario validation ------------------------------------------------------------------


def test_validate_scenario_empty_errors_for_well_formed():
    assert validate_scenario(_VALID) == []


def test_validate_scenario_rejects_non_dict():
    errors = validate_scenario([])
    assert errors == ["scenario: must be a JSON object"]


def test_validate_scenario_reports_missing_required_keys():
    errors = validate_scenario({"id": "x"})
    assert any("missing required keys" in err for err in errors)


def test_validate_scenario_rejects_empty_id():
    bad = dict(_VALID, id="  ")
    assert any("id must be a non-empty string" in err for err in validate_scenario(bad))


@pytest.mark.parametrize("winner", ["A", "B", "tie"])
def test_validate_scenario_accepts_valid_winners(winner):
    assert validate_scenario(dict(_VALID, expected_winner=winner)) == []


def test_validate_scenario_rejects_invalid_winner():
    bad = dict(_VALID, expected_winner="C")
    assert any("expected_winner must be one of" in err for err in validate_scenario(bad))


# --- Manifest and corpus loading ----------------------------------------------------------


def test_load_manifest_requires_object_with_scenarios():
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


def test_load_corpus_rejects_manifest_id_mismatch():
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "corpus")
        scenarios = os.path.join(root, "scenarios")
        os.makedirs(scenarios)
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"scenarios": [{"id": "listed", "file": "one.json"}]}, f)
        with open(os.path.join(scenarios, "one.json"), "w", encoding="utf-8") as f:
            json.dump(dict(_VALID, id="inside-file"), f)
        with pytest.raises(ValueError, match="does not match"):
            load_corpus(root)


# --- Scenario replay ----------------------------------------------------------------------


def test_run_scenario_reports_pass_and_required_fields():
    row = run_scenario(_VALID)
    assert row["passed"] is True
    assert row["actual_winner"] == "A"
    assert row["expected_winner"] == "A"
    for key in ("id", "description", "judge_order", "detail"):
        assert key in row


def test_run_scenario_reports_fail_on_mismatch():
    row = run_scenario(dict(_VALID, expected_winner="B"))
    assert row["passed"] is False
    assert "expected B" in row["detail"]


# --- Symmetry check -----------------------------------------------------------------------


def test_check_symmetry_skipped_when_not_requested():
    assert check_symmetry(_VALID) is None


def test_check_symmetry_passes_when_winners_flip():
    sym = dict(_VALID, expect_symmetric=True)
    row = check_symmetry(sym)
    assert row["passed"] is True
    assert row["forward"] == "A"
    assert row["backward"] == "B"
    for key in ("forward", "backward", "detail"):
        assert key in row


def test_check_symmetry_tie_stays_tie():
    tie = dict(
        _VALID,
        submission_b=_VALID["submission_a"],
        expected_winner="tie",
        expect_symmetric=True,
    )
    row = check_symmetry(tie)
    assert row["passed"] is True
    assert row["forward"] == row["backward"] == "tie"


# --- Calibration aggregation --------------------------------------------------------------


def test_check_calibration_passes_single_valid_scenario():
    result = check_calibration([_VALID])
    assert result["passed"] is True
    assert result["scenario_count"] == 1
    assert result["failed"] == []
    assert len(result["results"]) == 1


def test_check_calibration_fails_when_winner_mismatch():
    result = check_calibration([dict(_VALID, expected_winner="B")])
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


def test_failed_ids_list_skips_blank_and_non_string_entries(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _failed_ids_list([42, "", "  ", "good-id"]) == ["good-id"]
    assert any("failed[0]" in r.message for r in caplog.records)


def test_symmetry_checks_list_treats_non_list_as_empty(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(42) == []
    assert any("symmetry_checks is int" in r.message for r in caplog.records)


def test_symmetry_checks_list_skips_non_dict_rows(caplog):
    rows = [42, {"passed": True, "id": "sym-a", "detail": "ok"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        kept = _symmetry_checks_list(rows)
    assert len(kept) == 1
    assert any("symmetry_checks[0] is int" in r.message for r in caplog.records)


# --- Calibration headline -----------------------------------------------------------------


def test_calibration_headline_no_scenarios_for_non_dict():
    assert calibration_headline(None) == "calibration: no scenarios evaluated"
    assert calibration_headline({}) == "calibration: no scenarios evaluated"


def test_calibration_headline_pass_includes_count():
    good = check_calibration([_VALID])
    headline = calibration_headline(good)
    assert "PASS" in headline
    assert "1" in headline


def test_calibration_headline_fail_lists_failed_ids():
    bad = check_calibration([dict(_VALID, expected_winner="B")])
    headline = calibration_headline(bad)
    assert "FAIL" in headline
    assert "sample" in headline


def test_calibration_headline_survives_malformed_failed_and_symmetry_fields():
    assert "PASS" in calibration_headline(
        {"passed": True, "scenario_count": 3, "symmetry_checks": 42},
    )
    assert "FAIL" in calibration_headline(
        {"passed": False, "scenario_count": 3, "failed": 42},
    )


# --- Shipped corpus sanity (offline gate) -------------------------------------------------


def test_shipped_corpus_passes_calibration():
    result = check_calibration()
    assert result["passed"] is True
    assert result["scenario_count"] >= 1
    assert failed_scenarios(result) == []
