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
