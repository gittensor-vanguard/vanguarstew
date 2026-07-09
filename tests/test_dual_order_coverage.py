"""Tests for the dual-order coverage utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

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


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_non_utf8_file(tmp_path):
    # A non-UTF-8 file raises UnicodeDecodeError mid-read; the CLI must exit 2, not crash.
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"tasks": 10, "judge_order_stats": \xff}')
    assert cli.run([str(path)]) == 2


def test_cli_unreadable_path_is_handled(tmp_path):
    # Reading a directory raises IsADirectoryError (an OSError, like PermissionError) — exit 2.
    assert cli.run([str(tmp_path)]) == 2


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.dual_order_coverage"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
