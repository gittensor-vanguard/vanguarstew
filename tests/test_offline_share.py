"""Tests for offline share summary and CLI (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.offline_share import (  # noqa: E402
    _is_number,
    _slice_summary,
    offline_share_headline,
    summarize_offline_share,
)
from scripts import offline_share as cli  # noqa: E402


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
    assert _is_number(0) and _is_number(0.25)
    assert not _is_number(True)
    assert not _is_number("0.25")
    assert not _is_number(None)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))


def test_slice_summary_offline_share():
    out = _slice_summary(_stats(agree=2, disagree=0, tie=0, single=0, offline=2))
    assert out["total"] == 4
    assert out["offline"] == 2
    assert out["offline_share"] == 0.5


def test_zero_total_yields_none_share():
    out = _slice_summary(_stats(0, 0, 0, 0, 0))
    assert out["total"] == 0
    assert out["offline_share"] is None


def test_malformed_stats_yield_none():
    art = {"judge_order_stats": {"agree": 1, "offline": "many"}}
    assert _slice_summary(art)["offline_share"] is None


def test_negative_counts_rejected():
    assert _slice_summary(_stats(-1, 0, 0, 0, 0))["offline_share"] is None


def test_single_artifact_reports_share():
    summary = summarize_offline_share(_stats(agree=4, disagree=0, tie=0, single=0, offline=1))
    assert summary["kind"] == "single"
    assert summary["offline_share"] == 0.2
    assert summary["partitions"] is None


def test_missing_stats_yields_none():
    summary = summarize_offline_share({"composite_mean": 0.5})
    assert summary["offline_share"] is None


def test_generalization_reports_partitions_and_overall():
    summary = summarize_offline_share({
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=4, disagree=0, tie=0, single=0, offline=1),
    })
    assert summary["kind"] == "generalization"
    assert summary["offline"] == 1
    assert summary["total"] == 9
    assert summary["offline_share"] == round(1 / 9, 3)
    assert summary["partitions"]["tuned"]["offline_share"] == 0.0
    assert summary["partitions"]["held_out"]["offline_share"] == 0.2


def test_generalization_missing_partitions():
    summary = summarize_offline_share({
        "generalization_gap": 0.0,
        "tuned": {"judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0, "single": 0, "offline": 0}},
        "held_out": {},
    })
    assert summary["partitions"]["held_out"]["offline_share"] is None


def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1]):
        summary = summarize_offline_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["offline_share"] is None
        assert summary["partitions"] is None


def test_headline_variants():
    summary = summarize_offline_share(_stats(agree=2, disagree=0, tie=0, single=0, offline=2))
    assert "50.0%" in offline_share_headline(summary)
    assert offline_share_headline({"total": 0}) == "offline share: no judge stats available"
    assert offline_share_headline({}) == "offline share: no judge stats available"
    assert offline_share_headline("nope") == "offline share: no judge stats available"
    assert "n/a" in offline_share_headline({"total": 3, "offline": 1, "offline_share": None})


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_stats(agree=4, disagree=0, tie=0, single=0, offline=1)))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["offline_share"] == 0.2


def test_cli_generalization_reports_partitions(tmp_path, capsys):
    artifact = {
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=4, disagree=0, tie=0, single=0, offline=1),
    }
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["offline"] == 1


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
        [sys.executable, "-m", "scripts.offline_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
