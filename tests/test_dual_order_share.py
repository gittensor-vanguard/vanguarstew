"""Tests for dual-order share summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.dual_order_share import (  # noqa: E402
    dual_order_share_headline,
    summarize_dual_order_share,
)
from scripts import dual_order_share as cli  # noqa: E402


def _run(dual, judged, dual_flag=True):
    return {
        "judge_dual_order": dual_flag,
        "tally": {"challenger": judged // 2, "baseline": judged // 2, "tie": judged % 2},
        "judge_report": {
            "wins": judged // 2,
            "losses": judged // 2,
            "ties": judged % 2,
            "dual_order_tasks": dual,
            "disagreement_rate": 0.0,
        },
    }


def test_share_from_judge_report():
    out = summarize_dual_order_share(_run(4, 5))
    assert out["dual_order_tasks"] == 4
    assert out["judged_tasks"] == 5
    assert out["dual_order_share"] == 0.8


def test_all_dual_order_is_full_share():
    out = summarize_dual_order_share(_run(6, 6))
    assert out["dual_order_share"] == 1.0


def test_missing_telemetry_yields_none():
    out = summarize_dual_order_share({"composite_mean": 0.5})
    assert out["dual_order_share"] is None


def test_headline():
    out = summarize_dual_order_share(_run(2, 4))
    assert "50.0%" in dual_order_share_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_run(3, 3))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["dual_order_share"] == 1.0
