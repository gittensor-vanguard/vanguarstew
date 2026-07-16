"""Tests for win-rate summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.win_rate import summarize_win_rate, win_rate_headline  # noqa: E402
from scripts import win_rate as cli  # noqa: E402


def _run(tally):
    return {"composite_mean": 0.6, "tally": tally}


def test_rates_from_complete_tally():
    out = summarize_win_rate(_run({"challenger": 6, "baseline": 3, "tie": 1}))
    assert out["total"] == 10
    assert out["challenger_rate"] == 0.6
    assert out["baseline_rate"] == 0.3
    assert out["tie_rate"] == 0.1


def test_zero_total_yields_none_rates():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["total"] == 0
    assert out["challenger_rate"] is None


def test_missing_tally_yields_none():
    out = summarize_win_rate({"composite_mean": 0.5})
    assert out["total"] is None


def test_malformed_tally_yields_none():
    out = summarize_win_rate(_run({"challenger": 1, "baseline": "x", "tie": 0}))
    assert out["total"] is None


def test_negative_counts_rejected():
    out = summarize_win_rate(_run({"challenger": -1, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_float_counts_rejected():
    out = summarize_win_rate(_run({"challenger": 1.5, "baseline": 1, "tie": 0}))
    assert out["total"] is None


def test_non_dict_artifact_yields_none():
    out = summarize_win_rate("not-a-dict")
    assert out["total"] is None


def test_headline_happy_path():
    out = summarize_win_rate(_run({"challenger": 2, "baseline": 1, "tie": 0}))
    assert "challenger 2/3" in win_rate_headline(out)
    assert "66.7%" in win_rate_headline(out)


def test_headline_zero_total():
    out = summarize_win_rate(_run({"challenger": 0, "baseline": 0, "tie": 0}))
    assert win_rate_headline(out) == "win rate: no tally available"


def test_headline_with_nan_rate_does_not_crash():
    out = {
        "total": 3,
        "challenger": 1,
        "baseline": 1,
        "tie": 1,
        "challenger_rate": float("nan"),
    }
    assert "n/a" in win_rate_headline(out)


def test_single_repo_reports_kind_and_no_partitions():
    out = summarize_win_rate(_run({"challenger": 1, "baseline": 1, "tie": 0}))
    assert out["kind"] != "generalization"
    assert out["partitions"] is None


def test_multi_repo_reads_judge_report_when_no_top_level_tally():
    # run_multi_replay emits NO top-level tally for a multi-repo aggregate -- the win/loss/tie
    # counts live in judge_report (wins/losses/ties) -- so win_rate reported "no tally available".
    # Fall back to judge_report, mirroring margin_outlook / judge_wlt.
    art = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.55,
        "judge_report": {"wins": 5, "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}, {"repo": "r1", "tasks": 5}],
    }
    out = summarize_win_rate(art)
    assert out["kind"] == "multi"
    assert out["total"] == 10
    assert (out["challenger"], out["baseline"], out["tie"]) == (5, 3, 2)
    assert out["challenger_rate"] == 0.5


def test_top_level_tally_takes_precedence_over_judge_report():
    # When both are present the explicit tally wins; judge_report is only the fallback.
    out = summarize_win_rate({
        "tally": {"challenger": 1, "baseline": 0, "tie": 0},
        "judge_report": {"wins": 9, "losses": 9, "ties": 9},
    })
    assert out["total"] == 1 and out["challenger"] == 1


def test_malformed_judge_report_fallback_fails_closed():
    # A malformed judge_report (negative count) is rejected the same way a malformed tally is.
    out = summarize_win_rate({
        "judge_report": {"wins": -1, "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}],
    })
    assert out["total"] is None


def test_non_dict_judge_report_fallback_yields_none():
    # A non-dict judge_report is ignored (fails closed), just like a non-dict tally.
    out = summarize_win_rate({"judge_report": "nope", "per_repo": [{"repo": "r0", "tasks": 5}]})
    assert out["total"] is None


def test_zero_count_judge_report_yields_zero_total_none_rates():
    # An all-zero judge_report is a valid empty tally: total 0, rates None (matches the zero-tally
    # case), not "unavailable".
    out = summarize_win_rate({
        "judge_report": {"wins": 0, "losses": 0, "ties": 0},
        "per_repo": [{"repo": "r0", "tasks": 0}],
    })
    assert out["total"] == 0
    assert out["challenger_rate"] is None


def test_judge_report_missing_key_fails_closed():
    # Every one of wins/losses/ties must be present; a judge_report missing a key fails closed.
    out = summarize_win_rate({
        "judge_report": {"wins": 5, "losses": 3},          # no "ties"
        "per_repo": [{"repo": "r0", "tasks": 5}],
    })
    assert out["total"] is None


def test_judge_report_non_int_value_fails_closed():
    # A non-integer judge_report count is rejected the same way a non-int tally count is.
    out = summarize_win_rate({
        "judge_report": {"wins": "5", "losses": 3, "ties": 2},
        "per_repo": [{"repo": "r0", "tasks": 5}],
    })
    assert out["total"] is None


# --- generalization: sum the tuned/held_out partition tallies (mirrors offline_share) --------

def _gen(tuned_tally, held_tally):
    art = {"generalization_gap": 0.0}
    if tuned_tally is not None:
        art["tuned"] = {"tally": tuned_tally}
    if held_tally is not None:
        art["held_out"] = {"tally": held_tally}
    return art


def test_generalization_sums_partition_tallies():
    out = summarize_win_rate(_gen({"challenger": 4, "baseline": 1, "tie": 1},
                                  {"challenger": 1, "baseline": 2, "tie": 0}))
    assert out["kind"] == "generalization"
    assert out["total"] == 9
    assert (out["challenger"], out["baseline"], out["tie"]) == (5, 3, 1)
    assert out["challenger_rate"] == 0.556        # 5/9
    assert out["partitions"]["tuned"]["total"] == 6
    assert out["partitions"]["held_out"]["total"] == 3


def test_generalization_missing_partition_yields_none_overall_but_keeps_partitions():
    out = summarize_win_rate({"generalization_gap": 0.0,
                              "tuned": {"tally": {"challenger": 4, "baseline": 1, "tie": 1}},
                              "held_out": {}})                       # no tally
    assert out["total"] is None                                     # can't combine a partial set
    assert out["partitions"]["tuned"]["total"] == 6                 # valid partition still reported
    assert out["partitions"]["held_out"]["total"] is None


def test_non_dict_partition_is_not_classified_generalization():
    # A non-dict partition is not a valid generalization set (artifact_kind -> not
    # "generalization"), so it falls back to the top-level tally (absent here) rather than
    # combining a partition that isn't there.
    out = summarize_win_rate({"generalization_gap": 0.0,
                              "tuned": "nope",
                              "held_out": {"tally": {"challenger": 1, "baseline": 0, "tie": 0}}})
    assert out["kind"] != "generalization"
    assert out["total"] is None
    assert out["partitions"] is None


def test_generalization_malformed_partition_tally_yields_none_overall():
    out = summarize_win_rate(_gen({"challenger": 4, "baseline": 1, "tie": 1},
                                  {"challenger": 1, "baseline": -1, "tie": 0}))  # negative count
    assert out["total"] is None
    assert out["partitions"]["held_out"]["total"] is None


def test_generalization_zero_total_yields_none_rates():
    out = summarize_win_rate(_gen({"challenger": 0, "baseline": 0, "tie": 0},
                                  {"challenger": 0, "baseline": 0, "tie": 0}))
    assert out["partitions"]["tuned"]["total"] == 0
    assert out["partitions"]["held_out"]["total"] == 0
    assert out["total"] is None
    assert out["challenger_rate"] is None


def test_generalization_overall_null_when_a_partition_has_zero_tasks():
    # A zero-task slice has integer (all-zero) counts but no defined challenger_rate; it must not
    # be summed into a plausible-but-wrong overall from the other partition alone -- the overall is
    # None, mirroring order_agree_rate (#1426), scored_fraction (#1274), skip_share (#1272), and
    # dual_order_coverage (#1280). The coherent partition's own rate is still reported under
    # ``partitions`` (#1496).
    art = {
        "generalization_gap": 0.0,
        "tuned": {"tally": {"challenger": 0, "baseline": 0, "tie": 0}},
        "held_out": {"tally": {"challenger": 6, "baseline": 3, "tie": 1}},
    }
    out = summarize_win_rate(art)
    assert out["partitions"]["tuned"]["total"] == 0
    assert out["partitions"]["tuned"]["challenger_rate"] is None
    assert out["partitions"]["held_out"]["challenger_rate"] == 0.6
    assert out["total"] is None
    assert out["challenger"] is None
    assert out["challenger_rate"] is None
    assert win_rate_headline(out) == "win rate: no tally available"


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run({"challenger": 1, "baseline": 1, "tie": 0}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["challenger_rate"] == 0.5


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory path raises IsADirectoryError inside open(); the CLI must report it cleanly and
    # exit 2, not dump a raw traceback (mirrors generalization_gate #1446 / objective_integrity #1377).
    assert cli.run([str(tmp_path)]) == 2
    assert "directory" in capsys.readouterr().err


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
