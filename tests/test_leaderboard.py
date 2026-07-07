"""Tests for the agent/run leaderboard ranking (deterministic, offline)."""

import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.leaderboard import (  # noqa: E402
    _components,
    _leaderboard_entries,
    _leaderboard_point,
    _leaderboard_unscored,
    leaderboard_headline,
    rank,
)


class _Weird:
    """A custom object that is not a (label, artifact) pair."""


def _single(score, judge=None, objective=None):
    art = {"composite_mean": score, "rows": []}
    if judge is not None or objective is not None:
        art["composite_parts"] = {"judge_mean": judge, "objective_mean": objective}
    return art


def _gen(tuned_score, judge=None, objective=None):
    tuned = {"composite_mean": tuned_score, "scored_repos": 3}
    if judge is not None or objective is not None:
        tuned["composite_parts"] = {"judge_mean": judge, "objective_mean": objective}
    return {
        "tuned": tuned,
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


def test_rank_orders_best_first_with_delta_from_best():
    out = rank([("A", _single(0.55)), ("B", _single(0.70)), ("C", _single(0.60))])
    assert [r["label"] for r in out["ranking"]] == ["B", "C", "A"]
    assert [r["rank"] for r in out["ranking"]] == [1, 2, 3]
    assert out["ranking"][0]["delta_from_best"] == 0.0
    assert out["ranking"][1]["delta_from_best"] == -0.10       # 0.60 - 0.70
    assert out["ranking"][2]["delta_from_best"] == -0.15       # 0.55 - 0.70
    assert out["best"] == {"label": "B", "composite_mean": 0.70}
    assert out["scored"] == 3 and out["total"] == 3


def test_rank_uses_competition_ranking_for_ties():
    # Two entries tie for the top score: they share rank 1 and the next rank skips to 3.
    out = rank([("A", _single(0.80)), ("B", _single(0.80)), ("C", _single(0.70))])
    assert [(r["label"], r["rank"]) for r in out["ranking"]] == [("A", 1), ("B", 1), ("C", 3)]
    assert out["ranking"][0]["delta_from_best"] == 0.0
    assert out["ranking"][1]["delta_from_best"] == 0.0


def test_ties_keep_input_order():
    out = rank([("second", _single(0.5)), ("first", _single(0.5))])
    assert [r["label"] for r in out["ranking"]] == ["second", "first"]


def test_rank_ranks_generalization_on_tuned_score():
    out = rank([("gen_hi", _gen(0.72)), ("single_lo", _single(0.40))])
    assert [r["label"] for r in out["ranking"]] == ["gen_hi", "single_lo"]
    assert out["best"]["composite_mean"] == 0.72


def test_unscored_artifacts_are_separated_never_ranked():
    out = rank([
        ("good", _single(0.6)),
        ("errored", {"error": "no tasks"}),
        ("malformed", {"composite_mean": "not-a-number"}),
        ("notdict", "oops"),
    ])
    assert [r["label"] for r in out["ranking"]] == ["good"]
    assert set(out["unscored"]) == {"errored", "malformed", "notdict"}
    assert out["scored"] == 1 and out["total"] == 4


def test_unscored_multi_repo_run_is_separated_never_ranked():
    # A multi-repo run that scored no repos (scored_repos: 0, placeholder 0.0) belongs in unscored,
    # not ranked as a real 0.0 that would skew the board.
    empty_run = {"repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
                 "per_repo": [{"repo": "a", "error": "bad path", "tasks": 0}]}
    out = rank([("cand_a", _single(0.6)), ("empty_run", empty_run)])
    assert [r["label"] for r in out["ranking"]] == ["cand_a"]
    assert out["unscored"] == ["empty_run"]
    assert out["scored"] == 1 and out["total"] == 2
    assert out["best"] == {"label": "cand_a", "composite_mean": 0.6}


def test_rank_empty_and_all_unscored():
    assert rank([])["best"] is None and rank([])["ranking"] == []
    allbad = rank([("a", {"error": "x"}), ("b", 123)])
    assert allbad["scored"] == 0 and allbad["best"] is None
    assert set(allbad["unscored"]) == {"a", "b"}


# --- #532: a non-list entries container must not abort rank -------------------------

_MALFORMED_ENTRIES = [42, 3.14, True, {"label": "A"}, "not a list"]


def test_leaderboard_entries_accepts_only_real_lists():
    rows = [("A", {"composite_mean": 0.5})]
    for bad in _MALFORMED_ENTRIES:
        assert _leaderboard_entries(bad) == [], bad
    assert _leaderboard_entries(rows) == rows
    assert _leaderboard_entries(None) == []


def test_rank_survives_non_list_entries():
    for bad in _MALFORMED_ENTRIES:
        out = rank(bad)
        assert out["best"] is None and out["ranking"] == [] and out["scored"] == 0, bad


def test_rank_logs_warning_for_non_list_entries(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        out = rank(42)
    assert out["scored"] == 0
    assert any("entries is int" in r.message for r in caplog.records)


# --- a malformed *entry* inside a valid entries list must be skipped, not crash rank ----------
# _leaderboard_entries (#532) guards a non-list container; _leaderboard_point extends that to the
# entries. Only a 2-element list/tuple is a valid (label, artifact) pair; everything else is
# skipped with a warning that names the offending value, and the scored entries around it rank.

_MALFORMED_POINTS = [
    42, 3.14, True, None, "ab", b"ab", (), ("only-one",), ("a", "b", "c"),
    ["a", "b", "c"], {"label": "A"}, _Weird(),
]


def test_leaderboard_point_accepts_only_two_element_pairs():
    assert _leaderboard_point(("A", {"composite_mean": 0.5})) == ("A", {"composite_mean": 0.5})
    assert _leaderboard_point(["A", {"composite_mean": 0.5}]) == ("A", {"composite_mean": 0.5})
    for bad in _MALFORMED_POINTS:
        assert _leaderboard_point(bad) is None, bad


def test_rank_survives_and_excludes_a_malformed_entry():
    # A single malformed entry (wrong length, not a list/tuple, bytes, or a custom object) is
    # skipped, and it is truly absent from the output: only the well-formed entries are ranked.
    for bad in _MALFORMED_POINTS:
        out = rank([("A", _single(0.55)), bad, ("B", _single(0.70))])
        assert out["scored"] == 2 and out["total"] == 2, bad
        assert [r["label"] for r in out["ranking"]] == ["B", "A"], bad   # ranked, malformed absent
        assert out["best"]["label"] == "B"


def test_rank_logs_the_index_and_content_of_a_malformed_entry(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        out = rank([("A", _single(0.5)), {"label": "B"}])
    assert out["scored"] == 1
    msg = " ".join(r.message for r in caplog.records)
    assert "entries[1]" in msg          # the offending index
    assert "dict" in msg                # the offending type
    assert "label" in msg               # the actual entry content, for debugging


def test_leaderboard_headline_names_the_leader_and_counts():
    out = rank([("A", _single(0.55)), ("B", _single(0.70)), ("C", _single(0.60))])
    line = leaderboard_headline(out)
    assert "B leads at 0.7" in line and "over 2 other(s)" in line

    with_unscored = rank([("A", _single(0.5)), ("bad", {"error": "x"})])
    assert "1 unscored" in leaderboard_headline(with_unscored)

    assert leaderboard_headline({}) == "leaderboard: no scored artifacts"
    assert leaderboard_headline(rank([])) == "leaderboard: no scored artifacts"


# --- #569: non-list unscored must not abort leaderboard_headline --------------------

_MALFORMED_UNSCORED_LISTS = [42, 3.14, True, "bad", "not a list"]


def test_leaderboard_unscored_accepts_only_real_lists():
    rows = ["bad"]
    for bad in _MALFORMED_UNSCORED_LISTS:
        assert _leaderboard_unscored(bad) == [], bad
    assert _leaderboard_unscored(rows) == rows
    assert _leaderboard_unscored(None) == []


def test_leaderboard_headline_survives_non_list_unscored():
    base = {"scored": 1, "best": {"label": "A", "composite_mean": 0.5}}
    for bad in _MALFORMED_UNSCORED_LISTS:
        line = leaderboard_headline({**base, "unscored": bad})
        assert "unscored" not in line, bad


def test_leaderboard_headline_logs_warning_for_non_list_unscored(caplog):
    import logging

    summary = {"scored": 1, "best": {"label": "A", "composite_mean": 0.5}, "unscored": 42}
    with caplog.at_level(logging.WARNING, logger="benchmark.leaderboard"):
        line = leaderboard_headline(summary)
    assert "unscored" not in line
    assert any("unscored is int" in r.message for r in caplog.records)


def test_single_scored_entry_leads_with_no_runners():
    out = rank([("solo", _single(0.5))])
    assert out["ranking"][0]["rank"] == 1
    assert out["ranking"][0]["delta_from_best"] == 0.0
    assert "over" not in leaderboard_headline(out)   # no "over N other(s)"


def test_ranking_rows_include_judge_and_objective_components():
    # Each row surfaces the components behind its score, from the headline partition.
    out = rank([
        ("A", _single(0.60, judge=0.7, objective=0.5)),
        ("B", _gen(0.72, judge=0.8, objective=0.6)),      # generalization -> read tuned's parts
    ])
    by_label = {r["label"]: r for r in out["ranking"]}
    assert by_label["A"]["judge_mean"] == 0.7 and by_label["A"]["objective_mean"] == 0.5
    assert by_label["B"]["judge_mean"] == 0.8 and by_label["B"]["objective_mean"] == 0.6


def test_components_are_none_when_parts_missing_or_malformed():
    out = rank([
        ("noparts", _single(0.5)),                                  # no composite_parts
        ("badparts", {"composite_mean": 0.4, "composite_parts": "oops"}),
    ])
    for row in out["ranking"]:
        assert row["judge_mean"] is None and row["objective_mean"] is None


def test_components_helper_reads_headline_partition_and_guards_non_dict():
    # Directly exercise the helper: it reads the top level, the tuned partition for a
    # generalization artifact, and returns None components for a non-dict.
    assert _components(_single(0.5, judge=0.7, objective=0.5)) == {"judge_mean": 0.7, "objective_mean": 0.5}
    assert _components(_gen(0.6, judge=0.8, objective=0.6)) == {"judge_mean": 0.8, "objective_mean": 0.6}
    assert _components("not-a-dict") == {"judge_mean": None, "objective_mean": None}
    assert _components({}) == {"judge_mean": None, "objective_mean": None}


def test_rank_does_not_mutate_inputs():
    entries = [("A", _single(0.5, judge=0.6, objective=0.4)), ("B", _gen(0.6))]
    snapshot = copy.deepcopy(entries)
    rank(entries)
    assert entries == snapshot


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.leaderboard", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_single(0.5)), encoding="utf-8")
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(f"a={good}", f"b={missing}")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_single(0.5)), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(f"a={good}", f"b={bad}")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_still_ranks_well_formed_artifacts(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps(_single(0.5)), encoding="utf-8")
    b = tmp_path / "b.json"
    b.write_text(json.dumps(_single(0.7)), encoding="utf-8")
    result = _run_cli(f"agentA={a}", f"agentB={b}")
    assert result.returncode == 0
    assert "leaderboard" in result.stderr.lower()
    summary = json.loads(result.stdout)
    assert summary["ranking"][0]["label"] == "agentB"
