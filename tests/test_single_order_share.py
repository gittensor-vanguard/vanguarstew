"""Tests for single-order share summary and CLI (deterministic, offline)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.single_order_share import (  # noqa: E402
    _is_number,
    _slice_summary,
    single_order_share_headline,
    summarize_single_order_share,
)
from scripts import single_order_share as cli  # noqa: E402


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


def test_slice_summary_single_order_share():
    out = _slice_summary(_stats(agree=2, disagree=0, tie=0, single=2, offline=0))
    assert out["total"] == 4
    assert out["single"] == 2
    assert out["single_order_share"] == 0.5


def test_zero_total_yields_none_share():
    out = _slice_summary(_stats(0, 0, 0, 0, 0))
    assert out["total"] == 0
    assert out["single_order_share"] is None


def test_malformed_stats_yield_none():
    art = {"judge_order_stats": {"agree": 1, "single": "many", "disagree": 0, "tie": 0, "offline": 0}}
    assert _slice_summary(art)["single_order_share"] is None


def test_negative_counts_rejected():
    assert _slice_summary(_stats(-1, 0, 0, 0, 0))["single_order_share"] is None


def test_single_artifact_reports_decimal_share():
    summary = summarize_single_order_share(_stats(agree=4, disagree=0, tie=0, single=1, offline=0))
    assert summary["kind"] == "single"
    assert summary["single_order_share"] == 0.2
    assert summary["partitions"] is None


def test_missing_stats_yields_none():
    summary = summarize_single_order_share({"composite_mean": 0.5})
    assert summary["single_order_share"] is None


def test_generalization_reports_partitions_and_overall():
    summary = summarize_single_order_share({
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=4, disagree=0, tie=0, single=1, offline=0),
    })
    assert summary["kind"] == "generalization"
    assert summary["single"] == 1
    assert summary["total"] == 9
    assert summary["single_order_share"] == round(1 / 9, 3)
    assert summary["partitions"]["tuned"]["single_order_share"] == 0.0
    assert summary["partitions"]["held_out"]["single_order_share"] == 0.2


def test_generalization_missing_partitions():
    summary = summarize_single_order_share({
        "generalization_gap": 0.0,
        "tuned": {"judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0, "single": 0, "offline": 0}},
        "held_out": {},
    })
    assert summary["partitions"]["held_out"]["single_order_share"] is None


def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1]):
        summary = summarize_single_order_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["single_order_share"] is None
        assert summary["partitions"] is None


def test_headline_formats_decimal_as_percentage():
    summary = summarize_single_order_share(_stats(agree=2, disagree=0, tie=0, single=2, offline=0))
    assert "50.0%" in single_order_share_headline(summary)
    assert single_order_share_headline({"total": 0}) == "single-order share: no judge stats available"
    assert single_order_share_headline({}) == "single-order share: no judge stats available"
    assert single_order_share_headline("nope") == "single-order share: no judge stats available"
    assert "n/a" in single_order_share_headline({"total": 3, "single": 1, "single_order_share": None})


def test_headline_nan_share_does_not_crash():
    assert "n/a" in single_order_share_headline({
        "total": 3,
        "single": 1,
        "single_order_share": float("nan"),
    })


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_stats(agree=4, disagree=0, tie=0, single=1, offline=0)))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["single_order_share"] == 0.2


def test_cli_generalization_reports_partitions(tmp_path, capsys):
    artifact = {
        "generalization_gap": 0.05,
        "tuned": _stats(agree=4, disagree=0, tie=0, single=0, offline=0),
        "held_out": _stats(agree=4, disagree=0, tie=0, single=1, offline=0),
    }
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["single"] == 1


def test_cli_missing_file(tmp_path, capsys):
    assert cli.run([str(tmp_path / "nope.json")]) == 2
    err = capsys.readouterr().err
    assert "artifact not found" in err and "Errno" not in err and "Traceback" not in err


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_directory_path_reports_distinct_error(tmp_path, capsys):
    # A real directory raises IsADirectoryError; name it distinctly instead of the raw errno.
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and str(tmp_path) in err
    assert "Errno" not in err and "Traceback" not in err


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root bypasses file-permission bits")
def test_cli_unreadable_file_reports_distinct_error(tmp_path, capsys):
    path = tmp_path / "locked.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        rc = cli.run([str(path)])
    finally:
        os.chmod(path, 0o644)
    assert rc == 2
    err = capsys.readouterr().err
    assert "artifact is not readable" in err and str(path) in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_broken_symlink_reports_distinct_error(tmp_path, capsys):
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "gone.json")
    assert cli.run([str(link)]) == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and str(link) in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_generic_oserror_reports_distinct_error(tmp_path, capsys, monkeypatch):
    def _raise(*args, **kwargs):
        raise OSError(5, "I/O error")

    monkeypatch.setattr("builtins.open", _raise)
    assert cli.run([str(tmp_path / "flaky.json")]) == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.single_order_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
