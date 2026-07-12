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


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory path raises IsADirectoryError from open() on POSIX (where CI runs), not a
    # FileNotFoundError -- it must exit 2 with an actionable message, not a raw traceback.
    assert cli.run([str(tmp_path)]) == 2
    assert "directory" in capsys.readouterr().err


def test_cli_unreadable_file_exits_two(tmp_path, capsys):
    # An unreadable regular file raises PermissionError from open() -- a distinct path from the
    # directory case -- and must also exit 2 with its own actionable message.
    path = tmp_path / "locked.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    if os.access(str(path), os.R_OK):  # root / a mode-ignoring filesystem can still read it
        os.chmod(path, 0o600)
        pytest.skip("file is readable despite chmod 0 (running as root?)")
    try:
        assert cli.run([str(path)]) == 2
        assert "not readable" in capsys.readouterr().err
    finally:
        os.chmod(path, 0o600)  # restore so pytest can remove tmp_path


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


def test_generalization_both_partitions_zero_total_yields_none_overall():
    # After the #1530 fix the overall is gated on each partition's derived decisive_rate being
    # non-None; two zero-task partitions both have a None rate, so the overall nulls out entirely
    # (total None), matching the sibling fixes rather than reporting a fabricated 0-of-0.
    out = summarize_decisive_rate(_gen({"challenger": 0, "baseline": 0, "tie": 0},
                                       {"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] is None
    assert out["decisive_rate"] is None


def test_generalization_asymmetric_zero_task_partition_nulls_overall():
    # #1530: a zero-task held_out partition has an integer (all-zero) total but a None rate. The
    # old gate (both totals are ints) summed it in, presenting the tuned partition's 0.8 as the
    # whole-run rate. The overall must now be None, while each partition still reports its own
    # figures (tuned coherent, held_out's rate None).
    out = summarize_decisive_rate(_gen({"challenger": 6, "baseline": 2, "tie": 2},   # tuned 8/10
                                       {"challenger": 0, "baseline": 0, "tie": 0}))  # held_out 0 tasks
    assert out["kind"] == "generalization"
    assert out["total"] is None
    assert out["decisive"] is None
    assert out["decisive_rate"] is None
    # partitions untouched: tuned keeps its real numbers; held_out reports its zero-task None rate
    assert out["partitions"]["tuned"]["total"] == 10
    assert out["partitions"]["tuned"]["decisive_rate"] == 0.8
    assert out["partitions"]["held_out"]["total"] == 0
    assert out["partitions"]["held_out"]["decisive_rate"] is None


def test_single_repo_reports_kind_and_null_partitions():
    out = summarize_decisive_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert out["kind"] != "generalization"
    assert out["partitions"] is None


def test_multi_repo_reads_judge_report_when_no_top_level_tally():
    # run_multi_replay emits NO top-level tally for a multi-repo aggregate -- the win/loss/tie
    # counts live in judge_report (wins/losses/ties) -- so decisive_rate reported "no tally
    # available". Fall back to judge_report, mirroring win_rate.
    art = {
        "repos": 2, "scored_repos": 2, "composite_mean": 0.55,
        "judge_report": {"wins": 5, "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}, {"repo": "r1", "tasks": 5}],
    }
    out = summarize_decisive_rate(art)
    assert out["kind"] == "multi"
    assert out["total"] == 10
    assert out["decisive"] == 8 and out["tie"] == 2
    assert out["decisive_rate"] == 0.8


def test_top_level_tally_takes_precedence_over_judge_report():
    # When both are present the explicit tally wins; judge_report is only the fallback.
    out = summarize_decisive_rate({
        "tally": {"challenger": 1, "baseline": 0, "tie": 0},
        "judge_report": {"wins": 9, "losses": 9, "ties": 9},
    })
    assert out["total"] == 1 and out["decisive"] == 1


def test_malformed_judge_report_fallback_fails_closed():
    out = summarize_decisive_rate({
        "judge_report": {"wins": -1, "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}],
    })
    assert out["total"] is None


@pytest.mark.parametrize("bad", ["nope", 42, [1, 2], None, 3.5])
def test_non_dict_judge_report_fallback_yields_none(bad):
    # A non-dict judge_report is ignored via the isinstance guard -> None, never an AttributeError
    # from calling .get() on a non-dict.
    out = summarize_decisive_rate({"judge_report": bad, "per_repo": [{"repo": "r0", "tasks": 5}]})
    assert out["total"] is None


@pytest.mark.parametrize("missing", ["wins", "losses", "ties"])
def test_judge_report_missing_any_key_fails_closed(missing):
    # Every one of wins/losses/ties must be present; a judge_report missing ANY single key fails
    # closed to None.
    report = {"wins": 5, "losses": 3, "ties": 2}
    del report[missing]
    out = summarize_decisive_rate({"judge_report": report, "per_repo": [{"repo": "r0", "tasks": 5}]})
    assert out["total"] is None


def test_judge_report_non_int_value_fails_closed():
    # A non-integer judge_report count is rejected the same way a non-int tally count is.
    out = summarize_decisive_rate({
        "judge_report": {"wins": "5", "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}],
    })
    assert out["total"] is None


def test_zero_count_judge_report_yields_zero_total_none_rates():
    # An all-zero judge_report is a valid empty tally: total 0, rates None, not "unavailable".
    out = summarize_decisive_rate({
        "judge_report": {"wins": 0, "losses": 0, "ties": 0},
        "per_repo": [{"repo": "r0", "tasks": 0}],
    })
    assert out["total"] == 0
    assert out["decisive_rate"] is None
