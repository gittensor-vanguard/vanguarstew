"""Tests for the offline objective-scoring golden corpus and calibration harness."""

import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_calibration import (  # noqa: E402
    _failed_ids_list,
    _is_number,
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
from benchmark.score_corpus import SCENARIOS_DIR  # noqa: E402

_VALID = {
    "id": "sample",
    "description": "sample scenario",
    "plan": [{"title": "fix loader", "kind": "bugfix", "files": ["core/loader.py"]}],
    "revealed": [{"subject": "fix: race in loader", "files": ["core/loader.py"]}],
    "expected": {"module_recall": 1.0, "objective_component": 1.0},
}


def test_shipped_corpus_passes_calibration():
    result = check_calibration()
    assert result["passed"] is True
    assert result["scenario_count"] == 13
    assert failed_scenarios(result) == []


def test_load_manifest_and_corpus_are_consistent():
    manifest = load_manifest()
    corpus = load_corpus()
    assert len(manifest["scenarios"]) == len(corpus)
    assert {scenario["id"] for scenario in corpus} == {entry["id"] for entry in manifest["scenarios"]}


def test_every_shipped_scenario_file_exists():
    manifest = load_manifest()
    for entry in manifest["scenarios"]:
        path = SCENARIOS_DIR / entry["file"]
        assert path.is_file(), entry["file"]
        scenario = load_scenario(path)
        assert scenario["id"] == entry["id"]


def test_validate_scenario_catches_missing_fields():
    errors = validate_scenario({"id": "x"})
    assert any("missing required keys" in err for err in errors)


def test_validate_scenario_rejects_empty_expected():
    bad = dict(_VALID, expected={})
    assert any("expected must be a non-empty object" in err for err in validate_scenario(bad))


def test_validate_scenario_rejects_bad_winner():
    bad = dict(_VALID, winner="Z", expected={"composite_score": 0.5})
    assert any("winner must be" in err for err in validate_scenario(bad))


def test_run_scenario_reports_pass_and_fail():
    passed = run_scenario(_VALID)
    assert passed["passed"] is True
    assert passed["actual"]["module_recall"] == 1.0
    failed = run_scenario(dict(_VALID, expected={"module_recall": 0.0}))
    assert failed["passed"] is False
    assert "module_recall" in failed["detail"]


def test_tolerance_is_configurable():
    scenario = dict(_VALID, expected={"module_recall": 0.999})
    assert run_scenario(scenario, tolerance=0.01)["passed"] is True
    assert run_scenario(scenario, tolerance=0.0001)["passed"] is False


def test_composite_scenario_in_shipped_corpus():
    scenario = load_scenario(SCENARIOS_DIR / "012-composite-score-blend.json")
    result = run_scenario(scenario)
    assert result["passed"] is True
    assert result["actual"]["composite_score"] == 0.667


def test_backlog_excluded_from_component_scenario():
    scenario = load_scenario(SCENARIOS_DIR / "009-backlog-excluded-from-component.json")
    result = run_scenario(scenario)
    assert result["passed"] is True
    assert result["actual"]["backlog_recall"] == 1.0
    assert result["actual"]["objective_component"] == 0.5


def test_calibration_headline_reports_pass_and_fail():
    ok = check_calibration([_VALID])
    assert "PASS" in calibration_headline(ok)
    bad = check_calibration([dict(_VALID, expected={"module_recall": 0.0})])
    assert "FAIL" in calibration_headline(bad)
    assert calibration_headline({}) == "score calibration: no scenarios evaluated"


def test_failed_scenarios_and_failed_ids_list_guard_malformed_rows():
    assert failed_scenarios({"failed": ["a", 42, ""]}) == ["a"]
    assert _failed_ids_list(42) == []


def test_failed_ids_list_logs_when_failed_is_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_calibration"):
        assert _failed_ids_list(42) == []
    assert any("not a list" in record.message for record in caplog.records)


def test_check_calibration_does_not_mutate_the_corpus():
    corpus = load_corpus()
    before = json.dumps(corpus, sort_keys=True)
    check_calibration(corpus)
    assert json.dumps(corpus, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_mismatch(tmp_path):
    bad = tmp_path / "bad-corpus"
    scenarios = bad / "scenarios"
    scenarios.mkdir(parents=True)
    manifest = {
        "name": "test",
        "version": 1,
        "description": "x",
        "scenarios": [{"id": "sample", "file": "001.json"}],
    }
    (bad / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (scenarios / "001.json").write_text(
        json.dumps(dict(_VALID, expected={"module_recall": 0.0})), encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.calibrate_score", "--corpus-root", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "FAIL" in proc.stderr


def test_cli_passes_for_shipped_corpus():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.calibrate_score", "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "PASS" in proc.stderr


def test_validate_scenario_rejects_non_dict():
    assert validate_scenario([])[0] == "scenario: must be a JSON object"


def test_load_manifest_rejects_bad_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_manifest(path)


# --- non-finite / oversized numeric values must fail a scenario, not crash the runner ---------
# json.load parses NaN/Infinity verbatim and a large JSON integer loads as an arbitrary-precision
# int; _values_match calls float() on such an `expected` value, which raised (OverflowError for an
# oversized int) and aborted the whole calibration run, contradicting the module's documented
# "malformed entries fail validation rather than crashing" contract.

_OVERSIZED_INT = int("1" + "0" * 400)  # finite Python int, but too large to convert to float


def test_is_number_rejects_non_finite_and_oversized_values():
    assert _is_number(0.0) is True
    assert _is_number(3) is True
    assert _is_number(-2.5) is True
    assert _is_number(True) is False          # bools are not numbers here
    assert _is_number("1.0") is False
    assert _is_number(None) is False
    assert _is_number(float("nan")) is False
    assert _is_number(float("inf")) is False
    assert _is_number(float("-inf")) is False
    assert _is_number(_OVERSIZED_INT) is False  # int too large for float -> not usable


def test_values_match_does_not_raise_on_non_finite_or_oversized_expected():
    # These previously raised inside float(); now they simply don't match a finite actual value.
    assert _values_match(_OVERSIZED_INT, 0.5, 0.001) is False
    assert _values_match(float("nan"), 0.5, 0.001) is False
    assert _values_match(float("inf"), 0.5, 0.001) is False
    # a real finite comparison still works
    assert _values_match(0.5, 0.5, 0.001) is True
    assert _values_match(0.5, 0.5004, 0.001) is True
    assert _values_match(0.5, 0.6, 0.001) is False


def test_values_match_does_not_raise_on_non_finite_or_oversized_actual():
    # Symmetric to the `expected` case: a corrupt value on the ACTUAL side must also fail the
    # finite guard and degrade to `==` rather than reaching float() and raising. `actual` is
    # normally a computed score, but the comparison must be safe regardless of which side is bad.
    assert _values_match(0.5, _OVERSIZED_INT, 0.001) is False
    assert _values_match(0.5, float("nan"), 0.001) is False
    assert _values_match(0.5, float("inf"), 0.001) is False
    # both sides corrupt: still no raise, still a mismatch
    assert _values_match(_OVERSIZED_INT, float("inf"), 0.001) is False


def test_failed_ids_list_drops_non_finite_items_without_coercion():
    # _failed_ids_list filters for non-empty strings only; a non-finite/oversized numeric id is
    # dropped, never coerced through float(), so it cannot raise OverflowError.
    assert _failed_ids_list(["ok", float("nan"), float("inf"), _OVERSIZED_INT, ""]) == ["ok"]
    assert failed_scenarios({"failed": [_OVERSIZED_INT, "keep"]}) == ["keep"]


def test_check_calibration_fails_not_crashes_on_a_corrupt_expected_value():
    # A scenario whose `expected` carries an oversized/non-finite number must fail (mismatch),
    # while a well-formed scenario in the same corpus still passes — no crash, per the contract.
    for bad in (_OVERSIZED_INT, float("nan"), float("inf")):
        corrupt = dict(_VALID, id="corrupt", expected={"module_recall": bad})
        result = check_calibration([_VALID, corrupt])   # must not raise
        assert result["passed"] is False
        assert result["failed"] == ["corrupt"]
        # the well-formed scenario is unaffected
        ok = next(r for r in result["results"] if r["id"] == "sample")
        assert ok["passed"] is True


def test_calibration_headline_tolerates_a_non_finite_scenario_count():
    # calibration_headline int()-converts scenario_count; a non-finite value from a hand-built
    # result must degrade to "no scenarios evaluated" rather than raising ValueError.
    for bad in (float("nan"), float("inf"), _OVERSIZED_INT):
        assert calibration_headline({"scenario_count": bad}) == "score calibration: no scenarios evaluated"
