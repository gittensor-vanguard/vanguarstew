"""Tests for decisive-rate summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.decisive_rate import decisive_rate_headline, summarize_decisive_rate  # noqa: E402
from scripts import decisive_rate as cli  # noqa: E402


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


def test_decisive_and_tie_shares_from_complete_tally():
    out = summarize_decisive_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out["total"] == 10
    assert out["decisive"] == 9
    assert out["tie"] == 1
    assert out["decisive_rate"] == 0.9
    assert out["tie_share"] == 0.1


def test_all_ties_yields_zero_decisive_rate():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 5}))
    assert out["decisive"] == 0
    assert out["decisive_rate"] == 0.0
    assert out["tie_share"] == 1.0


def test_zero_total_yields_none_rates():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["decisive_rate"] is None


def test_missing_tally_yields_none():
    out = summarize_decisive_rate({"composite_mean": 0.5})
    assert out["total"] is None


def test_malformed_tally_yields_none():
    out = summarize_decisive_rate(_run({"challenger": 1, "baseline": "x", "tie": 0}))
    assert out["total"] is None


def test_negative_counts_rejected():
    out = summarize_decisive_rate(_run({"challenger": -1, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_float_counts_rejected():
    out = summarize_decisive_rate(_run({"challenger": 1.5, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_non_dict_artifact_yields_none():
    out = summarize_decisive_rate("not-a-dict")
    assert out["total"] is None


def test_headline_happy_path():
    out = summarize_decisive_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert "3/3" in decisive_rate_headline(out)
    assert "100.0%" in decisive_rate_headline(out)


def test_headline_zero_total():
    out = summarize_decisive_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert decisive_rate_headline(out) == "decisive rate: no tally available"


def test_headline_with_nan_rate_does_not_crash():
    out = {
        "total": 3,
        "decisive": 2,
        "tie": 1,
        "decisive_rate": float("nan"),
        "tie_share": float("inf"),
    }
    headline = decisive_rate_headline(out)
    assert "n/a" in headline


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run({"challenger": 2, "baseline": 0, "tie": 2}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["decisive_rate"] == 0.5


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory artifact path is an OSError (IsADirectoryError on POSIX, PermissionError on
    # Windows), not a FileNotFoundError -- it must exit 2 with an actionable message, not a raw
    # traceback.
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "directory" in err or "not readable" in err


# --- generalization: sum the tuned/held_out partition tallies (mirrors win_rate) -------------

def _gen(tuned_tally, held_tally):
    art = {"generalization_gap": 0.0}
    if tuned_tally is not None:
        art["tuned"] = {"tally": tuned_tally}
    if held_tally is not None:
        art["held_out"] = {"tally": held_tally}
    return art


def test_generalization_sums_partition_tallies():
    # tuned 4/1/1 + held 1/2/0 -> 5 + 3 = 8 decisive of 9 tasks (only the tuned tie), i.e. 8/9.
    out = summarize_decisive_rate(_gen({"challenger": 4, "baseline": 1, "tie": 1},
                                       {"challenger": 1, "baseline": 2, "tie": 0}))
    assert out["kind"] == "generalization"
    assert out["total"] == 9
    assert out["decisive"] == 8
    assert out["tie"] == 1
    assert out["decisive_rate"] == 0.889          # 8/9
    assert out["tie_share"] == 0.111              # 1/9
    assert out["partitions"]["tuned"]["total"] == 6
    assert out["partitions"]["tuned"]["decisive"] == 5
    assert out["partitions"]["held_out"]["total"] == 3
    assert out["partitions"]["held_out"]["decisive"] == 3


def test_generalization_headline_reports_summed_rate():
    out = summarize_decisive_rate(_gen({"challenger": 4, "baseline": 1, "tie": 1},
                                       {"challenger": 1, "baseline": 2, "tie": 0}))
    assert "8/9" in decisive_rate_headline(out)


def test_generalization_missing_partition_yields_none_overall_but_keeps_partitions():
    out = summarize_decisive_rate({"generalization_gap": 0.0,
                                   "tuned": {"tally": {"challenger": 4, "baseline": 1, "tie": 1}},
                                   "held_out": {}})       # no tally
    assert out["kind"] == "generalization"
    assert out["total"] is None
    assert out["decisive_rate"] is None
    assert out["partitions"]["tuned"]["total"] == 6
    assert out["partitions"]["held_out"]["total"] is None


def test_generalization_both_partitions_zero_total_yields_none_rate():
    out = summarize_decisive_rate(_gen({"challenger": 0, "baseline": 0, "tie": 0},
                                       {"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["decisive_rate"] is None


def test_single_repo_reports_kind_and_null_partitions():
    out = summarize_decisive_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert out["kind"] != "generalization"
    assert out["partitions"] is None
