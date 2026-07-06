"""Tests for the position-disagreement share utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagree_share import (  # noqa: E402
    _slice_summary,
    disagree_share_headline,
    summarize_disagree_share,
)
from scripts import disagree_share as cli  # noqa: E402


def _stats(agree=0, disagree=0, tie=0, single=0, offline=0):
    return {"judge_order_stats": {
        "agree": agree, "disagree": disagree, "tie": tie, "single": single, "offline": offline}}


# --- single / multi ------------------------------------------------------------------------------

def test_single_share():
    summary = summarize_disagree_share(_stats(agree=3, disagree=2, tie=1))
    assert summary["kind"] == "single"
    assert summary == {"kind": "single", "total": 6, "disagree": 2, "disagree_share": 0.333,
                       "partitions": None}


def test_zero_total_is_none_share():
    summary = summarize_disagree_share(_stats())
    assert summary["total"] == 0
    assert summary["disagree_share"] is None


def test_missing_or_negative_or_non_integer_counts():
    assert summarize_disagree_share({"judge_order_stats": {"agree": 1}})["total"] is None   # missing keys
    assert summarize_disagree_share(_stats(agree=-1))["total"] is None                      # negative
    assert summarize_disagree_share(_stats(agree=1.5))["total"] is None                     # non-integer
    bad = _stats(agree=1)
    bad["judge_order_stats"]["disagree"] = True   # bool count
    assert summarize_disagree_share(bad)["total"] is None


def test_non_dict_judge_order_stats():
    assert summarize_disagree_share({"judge_order_stats": "nope"})["disagree_share"] is None


# --- generalization ------------------------------------------------------------------------------

def test_generalization_partitions_and_overall():
    summary = summarize_disagree_share({
        "generalization_gap": 0.05,
        "tuned": _stats(agree=1, disagree=1),
        "held_out": _stats(agree=2, disagree=0),
    })
    assert summary["kind"] == "generalization"
    assert summary["total"] == 4 and summary["disagree"] == 1
    assert summary["disagree_share"] == 0.25
    assert summary["partitions"]["tuned"]["disagree_share"] == 0.5
    assert summary["partitions"]["held_out"]["disagree_share"] == 0.0


def test_generalization_malformed_partition_withholds_overall_without_raising():
    # A malformed partition must NOT reach sum() — the overall is withheld (None), no TypeError.
    summary = summarize_disagree_share({
        "generalization_gap": 0.0,
        "tuned": _stats(agree=1, disagree=1),
        "held_out": {},   # no stats
    })
    assert summary["total"] is None and summary["disagree_share"] is None
    assert summary["partitions"]["tuned"]["disagree_share"] == 0.5
    assert summary["partitions"]["held_out"]["disagree_share"] is None


# --- invalid / malformed -------------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts_never_raise():
    for bad in ({}, None, 5, "x", [1, 2],
                {"generalization_gap": 0, "tuned": None, "held_out": None},
                {"generalization_gap": 0, "tuned": {}, "held_out": {"judge_order_stats": None}}):
        summary = summarize_disagree_share(bad)
        assert summary["disagree_share"] is None
        assert isinstance(disagree_share_headline(summary), str)


# --- helpers / headline --------------------------------------------------------------------------

def test_slice_summary_helper():
    assert _slice_summary(None) == {"total": None, "disagree": None, "disagree_share": None}
    assert _slice_summary({"judge_order_stats": {
        "agree": 2, "disagree": 2, "tie": 0, "single": 0, "offline": 0}}) == {
        "total": 4, "disagree": 2, "disagree_share": 0.5}


def test_headline_variants():
    summary = summarize_disagree_share(_stats(agree=3, disagree=2, tie=1))
    assert disagree_share_headline(summary) == "disagree share: 33.3% (2/6 categorized task(s))"
    # Zero/missing total → "no judge stats available" (never a bare 0/0 share).
    assert disagree_share_headline({"total": 0}) == "disagree share: no judge stats available"
    assert disagree_share_headline({}) == "disagree share: no judge stats available"
    assert disagree_share_headline(None) == "disagree share: no judge stats available"
    # Positive total but non-numeric share/disagree degrade to n/a text, not a crash.
    assert disagree_share_headline({"total": 6, "disagree": None, "disagree_share": None}) == (
        "disagree share: n/a (n/a/6 categorized task(s))")


# --- CLI: success + every error path -------------------------------------------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_stats(agree=3, disagree=2, tie=1)))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["disagree_share"] == 0.333


def test_cli_generalization(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": _stats(agree=1, disagree=1),
                "held_out": _stats(agree=2, disagree=0)}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["tuned"]["disagree_share"] == 0.5


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_non_utf8_file(tmp_path):
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"judge_order_stats": \xff}')
    assert cli.run([str(path)]) == 2


def test_cli_unreadable_path_is_handled(tmp_path):
    assert cli.run([str(tmp_path)]) == 2


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run([sys.executable, "-m", "scripts.disagree_share"],
                          cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
