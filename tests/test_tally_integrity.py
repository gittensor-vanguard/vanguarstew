"""Tests for the judge tally integrity gate (deterministic, offline)."""

import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.tally_integrity import (  # noqa: E402
    _count_row_winners,
    _integrity_slices,
    _per_repo_list,
    _rows_list,
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
    if margin is not None:
        art["decisive_margin"] = margin
    elif margin is not False:
        art["decisive_margin"] = challenger - baseline
    return art


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_single_repo_passes():
    result = check_tally_integrity(_slice())
    assert result["passed"] is True
    assert _names(result) == [
        "tally_present", "tasks_reported", "tally_sums_to_tasks",
        "rows_match_tasks", "row_winners_match_tally", "decisive_margin_matches",
    ]


def test_tally_sum_mismatch_fails():
    art = _slice(tasks=4)
    art["tally"]["tie"] = 0
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_row_count_mismatch_fails():
    art = _slice()
    art["rows"] = art["rows"][:-1]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "rows_match_tasks" in failed_checks(result)


def test_row_winners_mismatch_fails():
    art = _slice()
    art["rows"][0]["winner"] = "baseline"
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "row_winners_match_tally" in failed_checks(result)


def test_decisive_margin_mismatch_fails():
    art = _slice(margin=99)
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


def test_missing_tally_fails():
    art = _slice()
    del art["tally"]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_present" in failed_checks(result)


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
            _slice(tasks=2, challenger=1, baseline=1, tie=0),
            {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}},
            _slice(tasks=1, challenger=1, baseline=0, tie=0),
        ],
    }
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "repo-0:tally_present" in _names(result)
    assert "repo-2:decisive_margin_matches" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_multi_repo_without_rows_still_checks_tally():
    entry = {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 1, "tie": 0},
        "decisive_margin": 1,
    }
    result = check_tally_integrity({"per_repo": [entry]})
    assert result["passed"] is True
    assert "repo-0:tally_sums_to_tasks" in _names(result)
    assert "rows_match_tasks" not in _names(result)


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.1,
        "tuned": {
            "scored_repos": 1,
            "per_repo": [_slice(tasks=2, challenger=2, baseline=0, tie=0)],
        },
        "held_out": {
            "scored_repos": 1,
            "per_repo": [_slice(tasks=1, challenger=0, baseline=1, tie=0)],
        },
    }
    result = check_tally_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:row_winners_match_tally" in _names(result)
    assert "held_out:repo-0:tally_sums_to_tasks" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_tally_counts_rejects_malformed_values():
    assert _tally_counts({"challenger": 1, "baseline": "x", "tie": 0}) is None
    assert _tally_counts("not a dict") is None


def test_count_row_winners_ignores_unknown_labels():
    rows = [{"winner": "challenger"}, {"winner": "unknown"}, {"winner": "tie"}]
    assert _count_row_winners(rows) == {"challenger": 1, "baseline": 0, "tie": 1}


def test_rows_list_skips_non_dict_rows(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        rows = _rows_list([{"winner": "tie"}, 42, "bad"])
    assert len(rows) == 1
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_per_repo_list_tolerates_non_list(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert _per_repo_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_tally_integrity_survives_malformed_per_repo(caplog):
    art = {"per_repo": [42, _slice(tasks=1, challenger=1, baseline=0, tie=0)]}
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        result = check_tally_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in _names(result))


def test_integrity_slices_expands_partition_rows():
    part = {"scored_repos": 1, "rows": _rows(1, 0, 0), "tasks": 1,
            "tally": {"challenger": 1, "baseline": 0, "tie": 0}}
    assert _integrity_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_tally_integrity(_slice()))
    art = _slice()
    art["tally"]["challenger"] = 99
    assert "INCONSISTENT" in integrity_headline(check_tally_integrity(art))


def test_check_tally_integrity_does_not_mutate_the_artifact():
    art = _slice()
    before = json.dumps(art, sort_keys=True)
    check_tally_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    art = _slice()
    art["decisive_margin"] = 99
    bad.write_text(json.dumps(art), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.tally_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_slice()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.tally_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr
