"""Tests for the judge report integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge import build_judge_report  # noqa: E402
from benchmark.judge_report_integrity import (  # noqa: E402
    _report_slices,
    check_judge_report_integrity,
    failed_checks,
    integrity_headline,
)


def _stats(agree=3, disagree=1, tie=1, single=0, offline=0):
    stats = {
        "agree": agree,
        "disagree": disagree,
        "tie": tie,
        "single": single,
        "offline": offline,
        "dual_order_tasks": agree + disagree + tie,
        "disagreement_rate": round(disagree / (agree + disagree + tie), 3),
    }
    return stats


def _artifact(tally=None, stats=None):
    tally = tally or {"challenger": 4, "baseline": 2, "tie": 1}
    stats = stats or _stats()
    return {
        "tasks": sum(int(tally[k]) for k in ("challenger", "baseline", "tie")),
        "tally": tally,
        "judge_order_stats": stats,
        "judge_report": build_judge_report(tally, stats),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_single_repo_passes():
    result = check_judge_report_integrity(_artifact())
    assert result["passed"] is True
    assert "wins_match_tally" in _names(result)
    assert "disagreement_rate_matches" in _names(result)


def test_mismatched_wins_fail():
    art = _artifact()
    art["judge_report"]["wins"] = 99
    result = check_judge_report_integrity(art)
    assert result["passed"] is False
    assert "wins_match_tally" in failed_checks(result)


def test_mismatched_disagreement_rate_fails():
    art = _artifact()
    art["judge_report"]["disagreement_rate"] = 0.99
    result = check_judge_report_integrity(art)
    assert result["passed"] is False
    assert "disagreement_rate_matches" in failed_checks(result)


def test_missing_judge_report_fails():
    art = _artifact()
    del art["judge_report"]
    result = check_judge_report_integrity(art)
    assert result["passed"] is False
    assert "report_present" in failed_checks(result)


def test_missing_judge_order_stats_fails():
    art = _artifact()
    del art["judge_order_stats"]
    result = check_judge_report_integrity(art)
    assert result["passed"] is False
    assert "stats_present" in failed_checks(result)


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_judge_report_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_judge_report_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(),
            {"tasks": 0},
            _artifact(tally={"challenger": 1, "baseline": 0, "tie": 0},
                      stats=_stats(agree=1, disagree=0, tie=0)),
        ],
    }
    result = check_judge_report_integrity(art)
    assert result["passed"] is True
    assert "repo-0:ties_match_tally" in _names(result)
    assert "repo-2:disagreements_match" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_generalization_checks_partition_level_report():
    stats = _stats()
    tally = {"challenger": 2, "baseline": 1, "tie": 0}
    partition = {
        "scored_repos": 1,
        "judge_order_stats": stats,
        "judge_report": build_judge_report(tally, stats),
    }
    report = {
        "generalization_gap": 0.05,
        "tuned": partition,
        "held_out": copy.deepcopy(partition),
    }
    result = check_judge_report_integrity(report)
    assert result["passed"] is True
    assert "tuned:dual_order_tasks_match" in _names(result)
    assert "held_out:report_present" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_judge_report_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_report_slices_expands_partition_per_repo():
    entry = _artifact()
    part = {"scored_repos": 1, "per_repo": [entry]}
    slices = _report_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned:repo-0", entry) in slices


def test_no_dual_order_tasks_allows_null_rate():
    stats = {"agree": 0, "disagree": 0, "tie": 0, "single": 2, "offline": 0,
             "dual_order_tasks": 0, "disagreement_rate": None}
    tally = {"challenger": 1, "baseline": 1, "tie": 0}
    art = {
        "tasks": 2,
        "tally": tally,
        "judge_order_stats": stats,
        "judge_report": build_judge_report(tally, stats),
    }
    assert check_judge_report_integrity(art)["passed"] is True


def test_malformed_per_repo_is_skipped(caplog):
    art = {"per_repo": [42, _artifact()]}
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_report_integrity"):
        result = check_judge_report_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in _names(result))


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_judge_report_integrity(_artifact()))
    art = _artifact()
    art["judge_report"]["losses"] = 0
    assert "INCONSISTENT" in integrity_headline(check_judge_report_integrity(art))


def test_check_judge_report_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_judge_report_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    art = _artifact()
    art["judge_report"]["disagreements"] = 99
    bad.write_text(json.dumps(art), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.judge_report_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_artifact()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.judge_report_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr
