"""Tests for the dual-order coverage utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_coverage import (  # noqa: E402
    _combined,
    _coverage,
    _slice_coverage,
    dual_order_coverage_headline,
    summarize_dual_order_coverage,
)
from scripts import dual_order_coverage as cli  # noqa: E402


def _slice(tasks=10, dual=4, **extra):
    slice_ = {"tasks": tasks, "judge_order_stats": {"dual_order_tasks": dual}, **extra}
    return slice_


# --- single / multi ------------------------------------------------------------------------------

def test_full_and_partial_coverage():
    assert summarize_dual_order_coverage(_slice(tasks=10, dual=10))["coverage"] == 1.0
    summary = summarize_dual_order_coverage(_slice(tasks=10, dual=4))
    assert summary["kind"] == "single"
    assert summary == {
        "kind": "single", "dual_order_tasks": 4, "tasks": 10, "coverage": 0.4, "partitions": None,
    }


def test_multi_reads_top_level_counts():
    summary = summarize_dual_order_coverage(_slice(tasks=8, dual=6, per_repo=[{}, {}]))
    assert summary["kind"] == "multi"
    assert summary["coverage"] == 0.75


def test_multi_sums_per_repo_when_no_top_level_tasks():
    # A real run_multi_replay result has no top-level `tasks`; the total lives in per_repo.
    # Without the per_repo fallback, coverage was n/a for every multi-repo run.
    summary = summarize_dual_order_coverage({
        "repos": 3, "scored_repos": 3,
        "judge_order_stats": {"dual_order_tasks": 9},
        "per_repo": [{"tasks": 3}, {"tasks": 3}, {"tasks": 3}],
    })
    assert summary["kind"] == "multi"
    assert summary["tasks"] == 9 and summary["coverage"] == 1.0


def test_generalization_partitions_derive_tasks_from_per_repo():
    # Each partition is a multi-repo result (per_repo, no top-level tasks); the overall sums both.
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.0,
        "tuned": {"judge_order_stats": {"dual_order_tasks": 6},
                  "per_repo": [{"tasks": 3}, {"tasks": 3}]},
        "held_out": {"judge_order_stats": {"dual_order_tasks": 2},
                     "per_repo": [{"tasks": 3}]},
    })
    assert summary["kind"] == "generalization"
    assert summary["tasks"] == 9 and summary["dual_order_tasks"] == 8
    assert summary["coverage"] == 0.889          # 8/9
    assert summary["partitions"]["tuned"]["coverage"] == 1.0
    assert summary["partitions"]["held_out"]["coverage"] == round(2 / 3, 3)


def test_task_total_fails_closed_on_malformed_per_repo():
    # A malformed per_repo entry (non-dict, or a non-integer/negative tasks) makes the total
    # untrustworthy -> None, rather than an undercount.
    for bad_per_repo in ([{"tasks": 3}, "oops"], [{"tasks": 3}, {"tasks": "x"}],
                         [{"tasks": 3}, {"tasks": -1}], []):
        summary = summarize_dual_order_coverage({
            "judge_order_stats": {"dual_order_tasks": 2}, "per_repo": bad_per_repo,
        })
        assert summary["tasks"] is None and summary["coverage"] is None


def test_zero_tasks_is_none_not_divide_by_zero():
    assert summarize_dual_order_coverage(_slice(tasks=0, dual=0))["coverage"] is None


def test_dual_exceeding_tasks_is_inconsistent_none():
    summary = summarize_dual_order_coverage(_slice(tasks=3, dual=5))
    assert summary["coverage"] is None       # not clamped/masked
    assert summary["dual_order_tasks"] == 5 and summary["tasks"] == 3  # raw counts still echoed


def test_missing_counts():
    assert summarize_dual_order_coverage({"tasks": 10})["coverage"] is None            # no stats
    assert summarize_dual_order_coverage({"judge_order_stats": {"dual_order_tasks": 4}})["tasks"] is None


def test_non_integer_and_bool_counts_rejected():
    assert summarize_dual_order_coverage(_slice(tasks=10.0, dual=4))["tasks"] is None    # float tasks
    assert summarize_dual_order_coverage(_slice(tasks=10, dual=True))["dual_order_tasks"] is None


def test_non_dict_judge_order_stats():
    summary = summarize_dual_order_coverage({"tasks": 10, "judge_order_stats": "nope"})
    assert summary["dual_order_tasks"] is None and summary["coverage"] is None


def test_negative_counts_rejected():
    assert summarize_dual_order_coverage(_slice(tasks=-1, dual=0))["tasks"] is None
    assert summarize_dual_order_coverage(_slice(tasks=10, dual=-2))["dual_order_tasks"] is None


# --- generalization ------------------------------------------------------------------------------

def test_generalization_partitions_and_overall():
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.05,
        "tuned": _slice(tasks=6, dual=6),
        "held_out": _slice(tasks=4, dual=2),
    })
    assert summary["kind"] == "generalization"
    assert summary["dual_order_tasks"] == 8 and summary["tasks"] == 10
    assert summary["coverage"] == 0.8
    assert summary["partitions"]["tuned"]["coverage"] == 1.0
    assert summary["partitions"]["held_out"]["coverage"] == 0.5


def test_generalization_partial_partition_yields_no_overall():
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.0,
        "tuned": _slice(tasks=6, dual=6),
        "held_out": {},   # no counts
    })
    assert summary["coverage"] is None            # overall withheld when a partition lacks counts
    assert summary["dual_order_tasks"] is None
    assert summary["partitions"]["tuned"]["coverage"] == 1.0
    assert summary["partitions"]["held_out"]["coverage"] is None


def test_generalization_overall_is_none_when_a_partition_is_incoherent():
    # An over-covered partition (dual_order_tasks > tasks) is malformed: its own coverage is None.
    # The overall must not sum the raw counts back into a plausible-but-wrong coverage (here 10
    # dual of 15 tasks -> 0.667); per _coverage's contract the inconsistency is surfaced, not masked.
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.0,
        "tuned": _slice(tasks=5, dual=8),      # incoherent: 8 dual-order tasks > 5 tasks
        "held_out": _slice(tasks=10, dual=2),
    })
    assert summary["coverage"] is None
    assert summary["dual_order_tasks"] is None and summary["tasks"] is None
    assert summary["partitions"]["tuned"]["coverage"] is None       # partition flagged malformed
    assert summary["partitions"]["held_out"]["coverage"] == 0.2     # the coherent one still shown


def test_generalization_overall_is_none_when_a_partition_has_zero_tasks():
    # A zero-task partition has no defined coverage, so the overall is withheld rather than summing
    # the remaining partition alone into a misleadingly complete figure.
    summary = summarize_dual_order_coverage({
        "generalization_gap": 0.0,
        "tuned": _slice(tasks=0, dual=0),      # zero-task slice -> coverage None
        "held_out": _slice(tasks=4, dual=2),
    })
    assert summary["coverage"] is None
    assert summary["dual_order_tasks"] is None and summary["tasks"] is None
    assert summary["partitions"]["tuned"]["coverage"] is None
    assert summary["partitions"]["held_out"]["coverage"] == 0.5


# --- invalid ------------------------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_dual_order_coverage(bad)
        assert summary["kind"] == "invalid"
        assert summary["coverage"] is None
        assert summary["partitions"] is None


def test_malformed_artifacts_never_raise():
    # Every public entry point coerces junk (via _dict) and guards counts, so no malformed artifact
    # or partition — None, wrong type, or missing keys — produces a runtime error.
    for bad in (
        None, {}, 5, "x", [1, 2],
        {"generalization_gap": 0, "tuned": None, "held_out": None},
        {"generalization_gap": 0, "tuned": {}, "held_out": {"judge_order_stats": None}},
        {"tasks": None, "judge_order_stats": {"dual_order_tasks": None}},
        {"tasks": "x", "judge_order_stats": "y"},
    ):
        summary = summarize_dual_order_coverage(bad)
        assert summary["coverage"] is None
        assert isinstance(dual_order_coverage_headline(summary), str)


def test_headline_tolerates_missing_and_wrong_typed_keys():
    # dual_order_coverage_headline never assumes a key is present or well-typed.
    assert dual_order_coverage_headline(None) == "dual-order coverage: n/a"
    assert dual_order_coverage_headline({}) == "dual-order coverage: n/a"
    assert dual_order_coverage_headline(
        {"coverage": {}, "dual_order_tasks": [], "tasks": "x"}) == "dual-order coverage: n/a"


# --- helpers -------------------------------------------------------------------------------------

def test_coverage_helper_branches():
    assert _coverage(4, 10) == 0.4
    assert _coverage(None, 10) is None
    assert _coverage(4, None) is None
    assert _coverage(0, 0) is None       # zero tasks
    assert _coverage(5, 3) is None       # dual > total


def test_slice_and_combined_helpers():
    assert _slice_coverage(None) == {"dual_order_tasks": None, "tasks": None, "coverage": None}
    both = _combined(_slice_coverage(_slice(tasks=6, dual=6)), _slice_coverage(_slice(tasks=4, dual=2)))
    assert both == {"dual_order_tasks": 8, "tasks": 10, "coverage": 0.8}
    partial = _combined(_slice_coverage(_slice(tasks=6, dual=6)), _slice_coverage({}))
    assert partial == {"dual_order_tasks": None, "tasks": None, "coverage": None}


# --- headline (the review's None-coverage TypeError) ---------------------------------------------

def test_headline_reports_and_degrades_gracefully():
    summary = summarize_dual_order_coverage(_slice(tasks=10, dual=4))
    assert dual_order_coverage_headline(summary) == (
        "dual-order coverage: 40.0% (4/10 tasks judged in both orders)")
    # None coverage must not raise in the percent formatter.
    assert dual_order_coverage_headline({"coverage": None, "dual_order_tasks": None, "tasks": None}) == (
        "dual-order coverage: n/a")
    assert dual_order_coverage_headline({}) == "dual-order coverage: n/a"
    assert dual_order_coverage_headline("nope") == "dual-order coverage: n/a"
    # Finite coverage but missing whole-number counts drops the detail clause.
    assert dual_order_coverage_headline({"coverage": 0.4, "dual_order_tasks": None, "tasks": 10}) == (
        "dual-order coverage: 40.0%")


# --- CLI: success + every error path (incl. the OSError/permission branch) ------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_slice(tasks=10, dual=4)))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"] == 0.4


def test_cli_generalization(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": _slice(tasks=6, dual=6), "held_out": _slice(tasks=4, dual=2)}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["held_out"]["coverage"] == 0.5


def test_cli_missing_file(tmp_path, capsys):
    path = tmp_path / "nope.json"
    assert cli.run([str(path)]) == 2
    err = capsys.readouterr().err
    assert "artifact not found" in err
    assert str(path) in err
    assert "Traceback" not in err


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_non_utf8_file(tmp_path, capsys):
    # A non-UTF-8 file raises UnicodeDecodeError mid-read; keep the distinct UTF-8 message.
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"tasks": 10, "judge_order_stats": \xff}')
    assert cli.run([str(path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "not valid UTF-8 JSON" in err


def test_cli_oversized_int_literal(tmp_path, capsys):
    # json.load raises a plain ValueError (not JSONDecodeError) for an oversized int literal.
    path = _write(tmp_path, "huge.json", '{"tasks": ' + "9" * 5000 + "}")
    assert cli.run([path]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "not valid JSON" in err
    assert "UTF-8" not in err


def test_cli_directory_path_reports_clean_error(tmp_path, capsys):
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err
    assert "[Errno" not in err
    assert "Traceback" not in err


def test_load_artifact_permission_error_is_clean(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact is not readable" in err
    assert "[Errno" not in err
    assert "Traceback" not in err


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.dual_order_coverage"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
