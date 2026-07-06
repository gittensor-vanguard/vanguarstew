"""Tests for the offline pairwise-judge golden corpus and calibration harness."""

import json
import logging
import os
import subprocess
import sys

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


# --- #625 / #852: malformed failed / symmetry_checks must not abort headlines --------

_MALFORMED_CONTAINERS = [
    42, 3.14, True, {"id": "x"}, "not a list",
    ({"id": "sym-a", "passed": True},),
    range(2),
]
_FALSY_SCALAR_CONTAINERS = [0, 0.0, False, ""]


def test_failed_ids_list_accepts_only_real_lists():
    rows = ["sample", "other"]
    for bad in _MALFORMED_CONTAINERS:
        assert _failed_ids_list(bad) == [], bad
    assert _failed_ids_list(rows) == rows
    assert _failed_ids_list(None) == []


def test_failed_ids_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _failed_ids_list(None) == []
    assert not caplog.records


def test_failed_ids_list_warns_for_each_skipped_entry(caplog):
    rows = [42, "", "  ", "good-id"]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _failed_ids_list(rows) == ["good-id"]
    messages = [r.message for r in caplog.records]
    assert any("failed[0]" in m for m in messages)
    assert any("failed[1]" in m for m in messages)
    assert not any("no usable scenario ids" in m for m in messages)


def test_failed_ids_list_warns_when_every_entry_is_unusable(caplog):
    rows = [42, None, ""]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _failed_ids_list(rows) == []
    messages = [r.message for r in caplog.records]
    assert any("failed[0]" in m for m in messages)
    assert any("no usable scenario ids" in m for m in messages)


def test_symmetry_checks_list_accepts_only_real_lists():
    rows = [{"id": "sym-a", "passed": True}]
    for bad in _MALFORMED_CONTAINERS:
        assert _symmetry_checks_list(bad) == [], bad
    assert _symmetry_checks_list(rows) == rows
    assert _symmetry_checks_list(None) == []
    assert _symmetry_checks_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CONTAINERS)
def test_symmetry_checks_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_symmetry_checks_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(None) == []
    assert not caplog.records


def test_symmetry_checks_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list([]) == []
    assert not caplog.records


def test_symmetry_checks_list_warns_for_tuple_container(caplog):
    row = ({"id": "sym-a", "passed": True},)
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(row) == []
    assert any("symmetry_checks is tuple" in r.message for r in caplog.records)


def test_symmetry_checks_list_warns_for_skipped_rows(caplog):
    rows = [42, {"passed": True, "id": "sym-a", "detail": "ok"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        kept = _symmetry_checks_list(rows)
    assert len(kept) == 1
    assert any("symmetry_checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_symmetry_checks_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("symmetry_checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_symmetry_checks_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"id": 42, "passed": True}, {"id": "sym-a", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("id is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_symmetry_checks_list_returns_only_valid_rows():
    valid = [
        {"id": "sym-a", "passed": False},
        {"id": "sym-b", "passed": True},
    ]
    assert _symmetry_checks_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"id": "", "passed": False},
        {"id": 99, "passed": False},
        {"id": "sym-a", "passed": 1},
        valid[1],
    ]
    assert _symmetry_checks_list(mixed) == valid


def test_symmetry_checks_list_accepts_native_bool_values():
    rows = [
        {"id": "sym-a", "passed": True},
        {"id": "sym-b", "passed": False},
    ]
    assert _symmetry_checks_list(rows) == rows


def test_symmetry_checks_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list([{"id": "sym-a", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_symmetry_checks_list_rejects_empty_id(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list([{"id": "", "passed": False}]) == []
    assert any("id is empty str" in r.message for r in caplog.records)


def test_symmetry_checks_list_accepts_numpy_bool_when_available():
    np = pytest.importorskip("numpy")
    for factory in (np.bool_, np.bool8):
        rows = [{"id": "sym-a", "passed": factory(True)}]
        assert _symmetry_checks_list(rows) == rows


def test_symmetry_checks_list_rejects_non_bool_passed_values(caplog):
    class AlmostBool:
        def __bool__(self):
            return True

    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        assert _symmetry_checks_list([{"id": "sym-a", "passed": AlmostBool()}]) == []
        assert _symmetry_checks_list([{"id": "sym-a", "passed": "true"}]) == []
    messages = [r.message for r in caplog.records]
    assert any("passed is AlmostBool" in m for m in messages)
    assert any("passed is str" in m for m in messages)


def test_calibration_headline_uses_sanitized_symmetry_count(caplog):
    checks = [{"id": "sym-a", "passed": True}, 42, {"id": "bad", "passed": 1}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        line = calibration_headline(
            {"passed": True, "scenario_count": 3, "symmetry_checks": checks},
        )
    assert line == "calibration: PASS (3 scenarios + 1 symmetry)"
    assert any("symmetry_checks[1] is int" in r.message for r in caplog.records)


def test_calibration_headline_ignores_unsanitized_rows_in_symmetry_count(caplog):
    checks = [
        {"id": "sym-a", "passed": True},
        {"id": "", "passed": True},
        {"id": "sym-b", "passed": 1},
        42,
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_calibration"):
        line = calibration_headline(
            {"passed": True, "scenario_count": 3, "symmetry_checks": checks},
        )
    assert line == "calibration: PASS (3 scenarios + 1 symmetry)"
    assert any("id is empty str" in r.message for r in caplog.records)
    assert any("passed is int" in r.message for r in caplog.records)
    assert any("symmetry_checks[3] is int" in r.message for r in caplog.records)


def test_failed_scenarios_and_headline_survive_malformed_fields():
    assert failed_scenarios({"failed": 42}) == []
    assert "PASS" in calibration_headline(
        {"passed": True, "scenario_count": 3, "symmetry_checks": 42},
    )
    assert "FAIL" in calibration_headline(
        {"passed": False, "scenario_count": 3, "failed": 42},
    )


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
