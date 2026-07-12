"""Tests for judge W-L-T summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge_wlt import judge_wlt_headline, summarize_judge_wlt  # noqa: E402
from scripts import judge_wlt as cli  # noqa: E402


def _run(wins=4, losses=2, ties=1):
    return {
        "composite_mean": 0.6,
        "judge_report": {
            "wins": wins,
            "losses": losses,
            "ties": ties,
            "dual_order_tasks": 3,
            "disagreement_rate": 0.0,
            "summary": "judge W-L-T",
        },
    }


def test_reads_wlt_from_judge_report():
    out = summarize_judge_wlt(_run(5, 3, 2))
    assert out["wins"] == 5
    assert out["losses"] == 3
    assert out["ties"] == 2
    assert out["total"] == 10
    assert out["kind"] == "single"


def test_multi_repo_kind_when_per_repo_present():
    art = _run()
    art["per_repo"] = []
    art["repos"] = 1
    art["scored_repos"] = 1
    out = summarize_judge_wlt(art)
    assert out["kind"] == "multi"


def test_single_repo_has_partitions_none():
    out = summarize_judge_wlt(_run(5, 3, 2))
    assert out["partitions"] is None


# --- generalization: sum the tuned/held_out partition reports (mirrors win_rate) -------------

def _gen(tuned_wlt, held_wlt):
    art = {"generalization_gap": 0.0}
    if tuned_wlt is not None:
        art["tuned"] = {"judge_report": dict(zip(("wins", "losses", "ties"), tuned_wlt))}
    if held_wlt is not None:
        art["held_out"] = {"judge_report": dict(zip(("wins", "losses", "ties"), held_wlt))}
    return art


def test_generalization_sums_partition_reports():
    out = summarize_judge_wlt(_gen((6, 3, 1), (5, 4, 1)))
    assert out["kind"] == "generalization"
    assert (out["wins"], out["losses"], out["ties"], out["total"]) == (11, 7, 2, 20)
    assert out["partitions"]["tuned"]["total"] == 10
    assert out["partitions"]["held_out"]["total"] == 10
    assert "11-7-2 over 20" in judge_wlt_headline(out)


def test_generalization_missing_partition_yields_none_overall_but_keeps_partitions():
    out = summarize_judge_wlt({"generalization_gap": 0.0,
                               "tuned": {"judge_report": {"wins": 6, "losses": 3, "ties": 1}},
                               "held_out": {}})                         # no judge_report
    assert out["total"] is None                                        # can't combine a partial set
    assert out["partitions"]["tuned"]["total"] == 10                   # valid partition still reported
    assert out["partitions"]["held_out"]["total"] is None


def test_generalization_malformed_partition_report_yields_none_overall():
    out = summarize_judge_wlt(_gen((6, 3, 1), (5, -4, 1)))             # negative count
    assert out["total"] is None
    assert out["partitions"]["held_out"]["total"] is None


def test_generalization_both_partitions_zero_task_null_overall():
    # Two zero-task partitions null the overall entirely rather than reporting a fabricated
    # 0-of-0 whole-run tally (matches the sibling zero-task generalization fixes).
    out = summarize_judge_wlt(_gen((0, 0, 0), (0, 0, 0)))
    assert out["total"] is None
    assert out["wins"] is None and out["losses"] is None and out["ties"] is None
    assert out["partitions"]["tuned"]["total"] == 0            # each partition still reported
    assert out["partitions"]["held_out"]["total"] == 0


def test_generalization_asymmetric_zero_task_partition_nulls_overall():
    # Regression for #1544: a zero-task ``tuned`` partition must not let ``held_out``'s tally be
    # summed and presented as the whole-run overall.
    out = summarize_judge_wlt(_gen((0, 0, 0), (6, 3, 1)))
    assert out["total"] is None
    assert out["wins"] is None
    assert out["partitions"]["tuned"]["total"] == 0            # zero-task partition preserved
    assert out["partitions"]["held_out"]["total"] == 10       # coherent partition preserved
    assert judge_wlt_headline(out) == "judge wlt: unavailable"


def test_missing_judge_report_yields_none():
    out = summarize_judge_wlt({"composite_mean": 0.5})
    assert out["total"] is None
    assert out["wins"] is None


def test_malformed_judge_report_yields_none():
    out = summarize_judge_wlt({"judge_report": "bad"})
    assert out["total"] is None


def test_negative_wins_rejected():
    out = summarize_judge_wlt(_run(wins=-1))
    assert out["total"] is None


def test_float_counts_rejected():
    art = _run()
    art["judge_report"]["wins"] = 1.5
    out = summarize_judge_wlt(art)
    assert out["total"] is None


def test_zero_total_yields_none_in_headline():
    out = summarize_judge_wlt(_run(0, 0, 0))
    assert out["total"] == 0
    assert judge_wlt_headline(out) == "judge wlt: unavailable"


def test_non_dict_artifact_kind_invalid():
    out = summarize_judge_wlt("not-a-dict")
    assert out["kind"] == "invalid"
    assert out["total"] is None


def test_headline_happy_path():
    out = summarize_judge_wlt(_run(2, 1, 0))
    assert judge_wlt_headline(out) == "judge wlt: 2-1-0 over 3 task(s)"


def test_headline_missing_data():
    assert judge_wlt_headline({}) == "judge wlt: unavailable"


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(3, 2, 1))
    assert cli.run([path]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["total"] == 6
    assert "judge wlt" in captured.err


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
    path.write_text("[1, 2]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err
