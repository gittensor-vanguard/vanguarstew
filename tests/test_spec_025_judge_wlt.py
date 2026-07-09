"""Contract tests for specs/025-benchmark-judge-wlt — assert judge_wlt.summarize_judge_wlt and
judge_wlt_headline satisfy the spec's EARS criteria: input guards, W-L-T extraction, artifact
kind, headline formatting, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_wlt import judge_wlt_headline, summarize_judge_wlt  # noqa: E402

_NON_DICT_ARTIFACTS = [None, 42, 3.14, True, "oops", [], (), b"bytes"]


def _artifact(wins=4, losses=2, ties=1, **extra):
    body = {
        "composite_mean": 0.6,
        "judge_report": {"wins": wins, "losses": losses, "ties": ties},
    }
    body.update(extra)
    return body


# --- Input guard --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_DICT_ARTIFACTS)
def test_non_dict_artifact_kind_invalid_and_counts_none(bad):
    out = summarize_judge_wlt(bad)
    assert out["kind"] == "invalid"
    assert out["wins"] is None
    assert out["losses"] is None
    assert out["ties"] is None
    assert out["total"] is None


# --- W-L-T extraction ---------------------------------------------------------------------


def test_reads_valid_wlt_from_judge_report():
    out = summarize_judge_wlt(_artifact(5, 3, 2))
    assert out["wins"] == 5
    assert out["losses"] == 3
    assert out["ties"] == 2
    assert out["total"] == 10


def test_malformed_judge_report_yields_none_counts():
    assert summarize_judge_wlt({"judge_report": "bad"})["total"] is None
    assert summarize_judge_wlt({"judge_report": None})["total"] is None
    assert summarize_judge_wlt({})["total"] is None


def test_negative_and_float_counts_rejected():
    assert summarize_judge_wlt(_artifact(wins=-1))["total"] is None
    art = _artifact()
    art["judge_report"]["wins"] = 1.5
    assert summarize_judge_wlt(art)["total"] is None


def test_bool_counts_rejected():
    art = _artifact()
    art["judge_report"]["wins"] = True
    assert summarize_judge_wlt(art)["total"] is None


# --- Zero total ---------------------------------------------------------------------------


def test_zero_total_is_zero_not_none():
    out = summarize_judge_wlt(_artifact(0, 0, 0))
    assert out["total"] == 0
    assert out["wins"] == 0
    assert out["losses"] == 0
    assert out["ties"] == 0


# --- Artifact kind ------------------------------------------------------------------------


def test_kind_from_artifact_kind():
    assert summarize_judge_wlt(_artifact())["kind"] == "single"
    multi = _artifact()
    multi["per_repo"] = []
    assert summarize_judge_wlt(multi)["kind"] == "multi"
    gen = {
        "tuned": {"per_repo": []},
        "held_out": {"per_repo": []},
        "generalization_gap": 0.1,
        "judge_report": {"wins": 1, "losses": 0, "ties": 0},
    }
    assert summarize_judge_wlt(gen)["kind"] == "generalization"


# --- Headline — unavailable ---------------------------------------------------------------


def test_headline_unavailable_on_zero_total():
    out = summarize_judge_wlt(_artifact(0, 0, 0))
    assert judge_wlt_headline(out) == "judge wlt: unavailable"


def test_headline_unavailable_on_missing_counts():
    assert judge_wlt_headline({}) == "judge wlt: unavailable"
    assert judge_wlt_headline({"total": 5, "wins": None}) == "judge wlt: unavailable"


def test_headline_non_dict_summary_treated_as_empty():
    assert judge_wlt_headline([]) == "judge wlt: unavailable"


# --- Headline — happy path ----------------------------------------------------------------


def test_headline_happy_path():
    out = summarize_judge_wlt(_artifact(2, 1, 0))
    assert judge_wlt_headline(out) == "judge wlt: 2-1-0 over 3 task(s)"


# --- Pure evaluation ----------------------------------------------------------------------


def test_does_not_mutate_artifact():
    art = _artifact(3, 2, 1)
    snapshot = copy.deepcopy(art)
    summarize_judge_wlt(art)
    assert art == snapshot


def test_no_io_imports():
    import benchmark.judge_wlt as mod

    source = open(mod.__file__, encoding="utf-8").read()
    assert "open(" not in source
    assert "requests" not in source
    assert "urllib" not in source
