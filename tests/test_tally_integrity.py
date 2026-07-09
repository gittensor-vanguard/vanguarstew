"""Tests for the judge tally integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.tally_integrity import (  # noqa: E402
    _check_rows_list,
    _count_row_winners,
    _integrity_slices,
    _tally_counts,
    check_tally_integrity,
    failed_checks,
    integrity_headline,
)


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


def test_a_consistent_single_repo_passes():
    result = check_tally_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "tally_present", "tasks_reported", "tally_sums_to_tasks",
        "rows_match_tasks", "row_winners_match_tally", "decisive_margin_matches",
    ]


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
    art = _artifact(margin=99)
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


def test_missing_tally_fails_tally_present():
    art = _artifact()
    del art["tally"]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_present" in failed_checks(result)
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_missing_tasks_fails_tasks_reported():
    art = _artifact()
    del art["tasks"]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tasks_reported" in failed_checks(result)


def test_zero_tasks_slice_is_not_selected():
    result = check_tally_integrity({"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_slice_without_rows_skips_row_checks():
    entry = {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 1, "tie": 0},
        "decisive_margin": 1,
    }
    result = check_tally_integrity({"per_repo": [entry]})
    assert result["passed"] is True
    assert "rows_match_tasks" not in _names(result)


def test_slice_without_decisive_margin_skips_margin_check():
    art = _artifact(margin=False)
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "decisive_margin_matches" not in _names(result)


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_tally_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_tally_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(tasks=2, challenger=1, baseline=1, tie=0),
            {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}},
            _artifact(tasks=1, challenger=1, baseline=0, tie=0),
        ],
    }
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "repo-0:row_winners_match_tally" in _names(result)
    assert "repo-2:decisive_margin_matches" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_generalization_checks_each_scored_partition():
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
    assert "tuned:repo-0:tally_sums_to_tasks" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_per_repo_without_scored_repos_is_checked():
    held = _artifact()
    held["scored_repos"] = 1
    bad = _artifact(tasks=3, challenger=2, baseline=1, tie=0)
    bad["tally"] = {"challenger": 0, "baseline": 3, "tie": 0}
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [bad]},
        "held_out": held,
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert any(name.startswith("tuned:repo-0:") for name in failed_checks(result))


def test_tally_counts_rejects_malformed_values():
    assert _tally_counts({"challenger": 1, "baseline": "x", "tie": 0}) is None
    assert _tally_counts("not a dict") is None


def test_count_row_winners_ignores_unknown_labels():
    rows = [{"winner": "challenger"}, {"winner": "unknown"}, {"winner": "tie"}]
    assert _count_row_winners(rows) == {"challenger": 1, "baseline": 0, "tie": 1}


def test_malformed_rows_are_skipped_with_warning(caplog):
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


def test_malformed_per_repo_survives(caplog):
    art = {"per_repo": [42, _artifact(tasks=1, challenger=1, baseline=0, tie=0)]}
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        result = check_tally_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in _names(result))


def test_integrity_slices_expands_partition_rows():
    part = {"scored_repos": 1, "rows": _rows(1, 0, 0), "tasks": 1,
            "tally": {"challenger": 1, "baseline": 0, "tie": 0}}
    slices = _integrity_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned", part) in slices


def test_every_check_reported_when_several_fail():
    art = _artifact()
    art["tally"]["challenger"] = 99
    art["decisive_margin"] = 99
    result = check_tally_integrity(art)
    assert len(result["checks"]) == 6
    assert result["passed"] is False


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_tally_integrity(_artifact()))
    art = _artifact()
    art["tally"]["challenger"] = 99
    assert "INCONSISTENT" in integrity_headline(check_tally_integrity(art))


def test_integrity_headline_survives_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "tally integrity: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


# --- checks row sanitization for tally integrity headlines ---------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "tally_present"}, "not a list",
    ({"name": "tally_present", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "tally_present", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "tally_present", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "tally integrity: INCONSISTENT (1/1 checks failed: tally_present)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert failed_checks({"checks": checks}) == ["tally_present"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_tally_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_tally_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.tally_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_consistent_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_artifact()), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "CONSISTENT" in result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    path = tmp_path / "bad.json"
    art = _artifact()
    art["decisive_margin"] = 99
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INCONSISTENT" in result.stderr


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    result = _run_cli(str(missing), "--strict")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "No such file" in result.stderr


def test_cli_reports_clean_error_for_non_object_artifact(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "must be a JSON object" in result.stderr


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
