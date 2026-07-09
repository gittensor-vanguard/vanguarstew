"""Contract tests for specs/032-benchmark-freeze-coverage — assert freeze_coverage.py
satisfies the spec's EARS criteria: freeze-commit detection, per-repo parsing, slice summaries,
artifact-kind branches, headline branches, logging, and pure evaluation. Offline, deterministic.
"""

import copy
import logging
import math
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze_coverage import (  # noqa: E402
    _dict,
    _has_freeze_commit,
    _is_number,
    _rows_from_per_repo,
    _slice_summary,
    freeze_coverage_headline,
    summarize_freeze_coverage,
)


def _repo(name, freeze=None, tasks=3):
    row = {"repo": name, "tasks": tasks}
    if freeze is not None:
        row["freeze_commit"] = freeze
    return row


def _multi(*rows):
    return {
        "repos": len(rows),
        "scored_repos": len(rows),
        "per_repo": list(rows),
    }


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    out = summarize_freeze_coverage(bad)
    assert out["kind"] == "invalid"
    assert out["repos_total"] == 0
    assert out["freeze_coverage"] is None


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}


# --- Freeze-commit detection ----------------------------------------------------------------


def test_has_freeze_commit_non_empty_str():
    assert _has_freeze_commit({"freeze_commit": "abc123"}) is True


@pytest.mark.parametrize(
    "entry",
    (
        {},
        {"freeze_commit": ""},
        {"freeze_commit": None},
        {"freeze_commit": 42},
        {"freeze_commit": True},
    ),
)
def test_empty_or_missing_freeze_not_counted(entry):
    assert _has_freeze_commit(entry) is False


# --- Per-repo row parsing -------------------------------------------------------------------


def test_per_repo_none_yields_empty_rows():
    assert _rows_from_per_repo(None) == []


def test_per_repo_non_list_warns_and_empty(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.freeze_coverage"):
        assert _rows_from_per_repo(42, field="per_repo") == []
    assert any("per_repo is int" in r.message for r in caplog.records)


def test_malformed_row_skipped_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.freeze_coverage"):
        rows = _rows_from_per_repo(["bad", _repo("a", "sha1")], field="per_repo")
    assert len(rows) == 1
    assert any("per_repo[0] is str" in r.message for r in caplog.records)


# --- Slice summary --------------------------------------------------------------------------


def test_slice_summary_computes_rate():
    stats = _slice_summary([_repo("a", "sha1"), _repo("b"), _repo("c", "sha2")])
    assert stats["repos_total"] == 3
    assert stats["repos_frozen"] == 2
    assert stats["freeze_coverage"] == round(2 / 3, 3)


def test_slice_summary_zero_rows_coverage_none():
    stats = _slice_summary([])
    assert stats["repos_total"] == 0
    assert stats["repos_frozen"] == 0
    assert stats["freeze_coverage"] is None


# --- Artifact-kind branches ---------------------------------------------------------------


def test_single_with_and_without_freeze():
    with_pin = summarize_freeze_coverage({"tasks": 5, "freeze_commit": "abc123"})
    assert with_pin["kind"] == "single"
    assert with_pin["repos_total"] == 1
    assert with_pin["repos_frozen"] == 1
    assert with_pin["freeze_coverage"] == 1.0
    assert with_pin["partitions"] is None

    without = summarize_freeze_coverage({"tasks": 5})
    assert without["repos_frozen"] == 0
    assert without["freeze_coverage"] == 0.0


def test_multi_repo_coverage():
    out = summarize_freeze_coverage(_multi(
        _repo("a", "sha1"),
        _repo("b"),
        _repo("c", "sha2"),
    ))
    assert out["kind"] == "multi"
    assert out["repos_total"] == 3
    assert out["repos_frozen"] == 2
    assert out["freeze_coverage"] == round(2 / 3, 3)
    assert out["partitions"] is None


def test_generalization_partitions_and_aggregate():
    art = {
        "tuned": _multi(_repo("a", "sha1"), _repo("b", "sha2")),
        "held_out": _multi(_repo("c"), _repo("d", "sha3")),
        "generalization_gap": 0.1,
    }
    out = summarize_freeze_coverage(art)
    assert out["kind"] == "generalization"
    assert out["repos_total"] == 4
    assert out["repos_frozen"] == 3
    assert out["freeze_coverage"] == round(3 / 4, 3)
    assert out["partitions"]["tuned"]["freeze_coverage"] == 1.0
    assert out["partitions"]["held_out"]["freeze_coverage"] == 0.5


def test_generalization_empty_partitions_aggregate_none():
    art = {
        "tuned": {"per_repo": []},
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_freeze_coverage(art)
    assert out["repos_total"] == 0
    assert out["freeze_coverage"] is None


def test_invalid_kind_returns_zeros():
    out = summarize_freeze_coverage({})
    assert out["kind"] == "invalid"
    assert out["repos_total"] == 0
    assert out["repos_frozen"] == 0
    assert out["freeze_coverage"] is None
    assert out["partitions"] is None


# --- Finite numeric semantics ---------------------------------------------------------------


def test_bool_and_non_finite_not_numeric():
    assert not _is_number(True)
    assert not _is_number(False)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert _is_number(0.0)
    assert _is_number(1)


# --- Freeze coverage headline ---------------------------------------------------------------


def test_headline_no_rows_when_zero_total():
    out = summarize_freeze_coverage({"per_repo": []})
    assert freeze_coverage_headline(out) == "freeze coverage: no per-repo rows"
    assert freeze_coverage_headline({"repos_total": 0, "kind": "multi"}) == (
        "freeze coverage: no per-repo rows"
    )
    assert freeze_coverage_headline({"repos_total": "two", "kind": "multi"}) == (
        "freeze coverage: no per-repo rows"
    )


def test_headline_multi_happy_path():
    out = summarize_freeze_coverage(_multi(_repo("a", "sha1"), _repo("b")))
    headline = freeze_coverage_headline(out)
    assert "50.0%" in headline
    assert "1/2" in headline
    assert "[" not in headline


def test_headline_generalization_includes_partitions():
    art = {
        "tuned": _multi(_repo("a", "sha1")),
        "held_out": _multi(_repo("b")),
        "generalization_gap": 0.0,
    }
    out = summarize_freeze_coverage(art)
    headline = freeze_coverage_headline(out)
    assert "tuned 100.0%" in headline
    assert "held-out 0.0%" in headline
    assert "1/2" in headline


def test_headline_nan_rate_shows_na():
    out = {
        "kind": "multi",
        "repos_total": 2,
        "repos_frozen": 1,
        "freeze_coverage": float("nan"),
        "partitions": None,
    }
    assert "n/a" in freeze_coverage_headline(out)
    assert math.isnan(out["freeze_coverage"])


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = _multi(_repo("a", "sha1"), _repo("b", "sha2"))
    snapshot = copy.deepcopy(art)
    summarize_freeze_coverage(art)
    assert art == snapshot
