"""Tests for the per-task row integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.row_integrity import (  # noqa: E402
    _row_slices,
    check_row_integrity,
    failed_checks,
    integrity_headline,
)
from benchmark.score import composite_score  # noqa: E402

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
            "judge_mean": round(sum(judge_parts[r["winner"]] for r in dict_rows) / len(dict_rows), 3),
            "objective_mean": round(sum(objective_parts) / len(dict_rows), 3),
        },
        "weights": {"judge": w_judge, "objective": w_objective},
        "rows": rows,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_single_repo_passes():
    result = check_row_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "rows_present", "row_composites_consistent", "composite_mean_matches_rows",
        "judge_mean_matches_rows", "objective_mean_matches_rows",
    ]


def test_wrong_row_composite_fails():
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


def test_tolerance_is_configurable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_row_integrity(art, tolerance=0.002)["passed"] is True
    assert check_row_integrity(art, tolerance=0.0005)["passed"] is False


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_row_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_row_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(),
            {"tasks": 0, "rows": []},
            _artifact(rows=ROWS[:1]),
        ],
    }
    result = check_row_integrity(art)
    assert result["passed"] is True
    assert "repo-0:composite_mean_matches_rows" in _names(result)
    assert "repo-2:row_composites_consistent" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "per_repo": [_artifact()]},
        "held_out": {"scored_repos": 1, "per_repo": [_artifact(rows=ROWS[:2])]},
    }
    result = check_row_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:judge_mean_matches_rows" in _names(result)
    assert "held_out:repo-0:rows_present" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_row_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_row_slices_expands_partition_rows():
    part = {"scored_repos": 1, "rows": ROWS, **_artifact(rows=ROWS)}
    slices = _row_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned", part) in slices


def test_malformed_rows_are_skipped_with_warning(caplog):
    art = {
        "tasks": 1,
        "composite_mean": 1.0,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": 1.0},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": [{"winner": "challenger", "objective": {"module_recall": 1.0},
                  "composite": 1.0}, 42],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        result = check_row_integrity(art)
    assert result["passed"] is True
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_row_integrity(_artifact()))
    art = _artifact()
    art["rows"][0]["composite"] = 0.0
    assert "INCONSISTENT" in integrity_headline(check_row_integrity(art))


def test_check_row_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_row_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    art = _artifact()
    art["rows"][0]["composite"] = 0.0
    bad.write_text(json.dumps(art), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.row_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_artifact()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.row_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr
