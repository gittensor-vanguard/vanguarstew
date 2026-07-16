"""Tests for dual-order share summary and CLI (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_share import (  # noqa: E402
    _is_number,
    _slice_summary,
    dual_order_share_headline,
    summarize_dual_order_share,
)
from scripts import dual_order_share as cli  # noqa: E402


def _stats(agree=3, disagree=1, tie=1, single=0, offline=0):
    return {
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
            "single": single,
            "offline": offline,
        },
    }


def test_is_number_accepts_finite_numbers_only():
    assert _is_number(0) and _is_number(0.75)
    assert not _is_number(True)
    assert not _is_number("0.75")
    assert not _is_number(None)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


def test_slice_summary_dual_order_share():
    out = _slice_summary(_stats(agree=2, disagree=1, tie=1, single=2, offline=0))
    assert out["total"] == 6
    assert out["dual_order_tasks"] == 4
    assert out["dual_order_share"] == round(4 / 6, 3)


def test_zero_total_yields_none_share():
    out = _slice_summary(_stats(0, 0, 0, 0, 0))
    assert out["total"] == 0
    assert out["dual_order_share"] is None


def test_malformed_stats_yield_none():
    art = {"judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0, "single": 0, "offline": 0}}
    assert _slice_summary(art)["dual_order_share"] is None


def test_negative_counts_rejected():
    assert _slice_summary(_stats(-1, 0, 0, 0, 0))["dual_order_share"] is None


def test_single_artifact_reports_decimal_share():
    summary = summarize_dual_order_share(_stats(agree=4, disagree=0, tie=0, single=1, offline=0))
    assert summary["kind"] == "single"
    assert summary["dual_order_tasks"] == 4
    assert summary["dual_order_share"] == 0.8
    assert summary["partitions"] is None


def test_missing_stats_yields_none():
    summary = summarize_dual_order_share({"composite_mean": 0.5})
    assert summary["dual_order_share"] is None


def test_generalization_reports_partitions_and_overall():
    summary = summarize_dual_order_share({
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=2, disagree=0, tie=0, single=2, offline=0),
    })
    assert summary["kind"] == "generalization"
    assert summary["dual_order_tasks"] == 6
    assert summary["total"] == 8
    assert summary["dual_order_share"] == 0.75
    assert summary["partitions"]["tuned"]["dual_order_share"] == 1.0
    assert summary["partitions"]["held_out"]["dual_order_share"] == 0.5


def test_generalization_missing_partitions():
    summary = summarize_dual_order_share({
        "generalization_gap": 0.0,
        "tuned": {"judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0, "single": 0, "offline": 0}},
        "held_out": {},
    })
    assert summary["partitions"]["held_out"]["dual_order_share"] is None


def test_generalization_overall_null_when_a_partition_has_zero_categorized_tasks():
    # A zero-task slice (all counts 0) has a None share; the multi-key dual-share overall must
    # not be summed from the coherent partition alone. Mirrors #1272/#1274/#1280.
    summary = summarize_dual_order_share({
        "generalization_gap": 0.0,
        "tuned": _stats(agree=0, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=6, disagree=0, tie=0, single=2, offline=0),
    })
    assert summary["partitions"]["tuned"]["dual_order_share"] is None
    assert summary["partitions"]["held_out"]["dual_order_share"] == 0.75
    assert summary["total"] is None
    assert summary["dual_order_tasks"] is None
    assert summary["dual_order_share"] is None


def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1]):
        summary = summarize_dual_order_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["dual_order_share"] is None
        assert summary["partitions"] is None


def test_headline_formats_decimal_as_percentage():
    summary = summarize_dual_order_share(_stats(agree=3, disagree=0, tie=0, single=2, offline=0))
    assert "60.0%" in dual_order_share_headline(summary)
    assert dual_order_share_headline({"total": 0}) == "dual-order share: no judge stats available"
    assert dual_order_share_headline({}) == "dual-order share: no judge stats available"
    assert dual_order_share_headline("nope") == "dual-order share: no judge stats available"
    assert "n/a" in dual_order_share_headline({"total": 3, "dual_order_tasks": 1, "dual_order_share": None})


def test_headline_nan_share_does_not_crash():
    assert "n/a" in dual_order_share_headline({
        "total": 3,
        "dual_order_tasks": 2,
        "dual_order_share": float("nan"),
    })


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_stats(agree=4, disagree=0, tie=0, single=1, offline=0)))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["dual_order_share"] == 0.8


def test_cli_generalization_reports_partitions(tmp_path, capsys):
    artifact = {
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=2, disagree=0, tie=0, single=2, offline=0),
    }
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["dual_order_tasks"] == 2


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_unreadable_path_is_handled(tmp_path):
    assert cli.run([str(tmp_path)]) == 2


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.dual_order_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
