"""Tests for the offline pairwise-judge golden corpus and calibration harness."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.judge_calibration import (  # noqa: E402
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
from benchmark.judge_corpus import CORPUS_DIR, MANIFEST_PATH, SCENARIOS_DIR  # noqa: E402

_VALID = {
    "id": "sample",
    "description": "sample scenario",
    "context": {"frozen_at": {"commit": "abc"}},
    "revealed": {"commits": []},
    "submission_a": {"philosophy": {"summary": "a"}, "plan": [{"title": "fix"}], "rationale": "x"},
    "submission_b": {"philosophy": {}, "plan": [], "rationale": ""},
    "expected_winner": "A",
}


def test_shipped_corpus_passes_calibration():
    result = check_calibration()
    assert result["passed"] is True
    assert result["scenario_count"] == 30
    assert failed_scenarios(result) == []


def test_load_manifest_and_corpus_are_consistent():
    manifest = load_manifest()
    corpus = load_corpus()
    assert len(manifest["scenarios"]) == len(corpus)
    assert {s["id"] for s in corpus} == {entry["id"] for entry in manifest["scenarios"]}


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


def test_validate_scenario_rejects_bad_winner():
    bad = dict(_VALID, expected_winner="C")
    assert any("expected_winner" in err for err in validate_scenario(bad))


def test_run_scenario_reports_pass_and_fail():
    passed = run_scenario(_VALID)
    assert passed["passed"] is True
    assert passed["actual_winner"] == "A"
    failed = run_scenario(dict(_VALID, expected_winner="B"))
    assert failed["passed"] is False


def test_check_symmetry_verifies_swap():
    sym = dict(_VALID, expect_symmetric=True)
    result = check_symmetry(sym)
    assert result["passed"] is True
    assert result["forward"] == "A"
    assert result["backward"] == "B"


def test_check_symmetry_skipped_when_not_requested():
    assert check_symmetry(_VALID) is None


def test_check_symmetry_tie_stays_tie():
    tie = dict(_VALID,
               submission_b=_VALID["submission_a"],
               expected_winner="tie",
               expect_symmetric=True)
    sym = check_symmetry(tie)
    assert sym["passed"] is True
    assert sym["forward"] == sym["backward"] == "tie"


def test_calibration_headline_pass_and_fail():
    good = check_calibration([_VALID])
    assert "PASS" in calibration_headline(good)
    bad = check_calibration([dict(_VALID, expected_winner="B")])
    assert "FAIL" in calibration_headline(bad)
    assert "sample" in calibration_headline(bad)
    assert calibration_headline({}) == "calibration: no scenarios evaluated"


def test_load_corpus_rejects_duplicate_ids(tmp_path):
    root = tmp_path / "corpus"
    scenarios = root / "scenarios"
    scenarios.mkdir(parents=True)
    manifest = {
        "scenarios": [
            {"id": "dup", "file": "a.json"},
            {"id": "dup", "file": "b.json"},
        ],
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in ("a.json", "b.json"):
        (scenarios / name).write_text(json.dumps(dict(_VALID, id="dup")), encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_corpus(root)


def test_load_corpus_rejects_manifest_id_mismatch(tmp_path):
    root = tmp_path / "corpus"
    scenarios = root / "scenarios"
    scenarios.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "scenarios": [{"id": "listed", "file": "one.json"}],
    }), encoding="utf-8")
    (scenarios / "one.json").write_text(json.dumps(dict(_VALID, id="inside-file")), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        load_corpus(root)


def test_malformed_scenario_file_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="missing required keys"):
        load_scenario(bad)


def test_check_calibration_does_not_mutate_corpus():
    corpus = load_corpus()
    snapshot = json.dumps(corpus, sort_keys=True)
    check_calibration(corpus)
    assert json.dumps(corpus, sort_keys=True) == snapshot


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.calibrate_judge", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def test_cli_passes_on_shipped_corpus():
    proc = _run_cli()
    assert proc.returncode == 0
    assert "calibration: PASS" in proc.stderr
    assert '"scenario_count": 30' in proc.stdout


def test_cli_strict_passes_on_shipped_corpus():
    proc = _run_cli("--strict")
    assert proc.returncode == 0


def test_cli_strict_fails_on_bad_corpus(tmp_path):
    root = tmp_path / "corpus"
    scenarios = root / "scenarios"
    scenarios.mkdir(parents=True)
    (root / "manifest.json").write_text(json.dumps({
        "scenarios": [{"id": "bad", "file": "bad.json"}],
    }), encoding="utf-8")
    (scenarios / "bad.json").write_text(json.dumps(dict(_VALID, id="bad", expected_winner="B")), encoding="utf-8")
    proc = _run_cli("--corpus-root", str(root), "--strict")
    assert proc.returncode == 1
    assert "calibration: FAIL" in proc.stderr


def test_cli_reports_loader_errors_cleanly(tmp_path):
    proc = _run_cli("--corpus-root", str(tmp_path / "missing"), "--strict")
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr


def test_symmetric_scenarios_in_shipped_corpus_all_pass():
    corpus = load_corpus()
    symmetric = [s for s in corpus if s.get("expect_symmetric")]
    assert len(symmetric) >= 20
    result = check_calibration(corpus)
    assert all(row["passed"] for row in result.get("symmetry_checks") or [])


def test_corpus_dir_paths_are_stable():
    assert MANIFEST_PATH.parent == CORPUS_DIR
    assert SCENARIOS_DIR.parent == CORPUS_DIR
