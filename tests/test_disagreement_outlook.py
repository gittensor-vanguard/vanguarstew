"""Tests for disagreement outlook summary and CLI (deterministic, offline)."""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.disagreement_outlook import (  # noqa: E402
    DEFAULT_STABLE_THRESHOLD,
    disagreement_outlook_headline,
    summarize_disagreement_outlook,
)
from scripts import disagreement_outlook as cli  # noqa: E402


def _run(rate=0.1, dual=4, source="judge_report"):
    return {
        "composite_mean": 0.6,
        source: {
            "dual_order_tasks": dual,
            "disagreement_rate": rate,
            "wins": 3,
            "losses": 1,
            "ties": 0,
        },
    }


def _partition_report(disagreements, dual):
    return {
        "judge_report": {
            "dual_order_tasks": dual,
            "disagreements": disagreements,
            "disagreement_rate": round(disagreements / dual, 3) if dual else None,
        }
    }


def test_stable_verdict_below_threshold():
    out = summarize_disagreement_outlook(_run(0.1, 5))
    assert out["verdict"] == "stable"
    assert out["disagreement_rate"] == 0.1
    assert out["dual_order_tasks"] == 5


def test_unstable_verdict_above_threshold():
    out = summarize_disagreement_outlook(_run(0.5, 3))
    assert out["verdict"] == "unstable"


def test_threshold_boundary_is_stable():
    out = summarize_disagreement_outlook(_run(DEFAULT_STABLE_THRESHOLD, 2))
    assert out["verdict"] == "stable"


def test_custom_threshold():
    out = summarize_disagreement_outlook(_run(0.25, 2), stable_threshold=0.2)
    assert out["verdict"] == "unstable"


def test_falls_back_to_judge_order_stats():
    art = {
        "composite_mean": 0.6,
        "judge_order_stats": {"dual_order_tasks": 2, "disagreement_rate": 0.0},
    }
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] == 2
    assert out["disagreements"] == 0
    assert out["disagreement_rate"] == 0.0


# --- #1253: stale judge_report.disagreement_rate must not override judge_order_stats --------


def test_stale_judge_report_rate_is_recomputed_from_stats():
    art = {
        "composite_mean": 0.7,
        "decisive_margin": 5,
        "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},
        "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.8
    assert out["disagreements"] == 8
    assert out["dual_order_tasks"] == 10
    assert out["verdict"] == "unstable"


def test_stats_plural_disagreements_overrides_stale_co_located_rate():
    art = {
        "composite_mean": 0.7,
        "judge_order_stats": {
            "dual_order_tasks": 10,
            "disagreements": 8,
            "disagreement_rate": 0.05,
        },
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.8
    assert out["disagreements"] == 8
    assert out["verdict"] == "unstable"


def test_disagreement_outlook_falls_back_to_report_when_stats_absent():
    art = {
        "composite_mean": 0.7,
        "judge_report": {"disagreement_rate": 0.25, "dual_order_tasks": 4},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.25
    assert out["disagreements"] == 1
    assert out["dual_order_tasks"] == 4
    assert out["verdict"] == "stable"


def test_disagreement_outlook_falls_back_to_report_when_stats_empty():
    art = {
        "composite_mean": 0.7,
        "judge_order_stats": {},
        "judge_report": {"disagreement_rate": 0.25, "dual_order_tasks": 4},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.25
    assert out["disagreements"] == 1
    assert out["verdict"] == "stable"


def test_consistent_report_rate_preserved_without_stats():
    art = _run(0.2, 5)
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] == 0.2
    assert out["disagreements"] == 1
    assert out["verdict"] == "stable"


def test_generalization_stale_disagreement_is_recomputed_on_tuned_partition():
    art = {
        "generalization_gap": 0.1,
        "tuned": {
            "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},
            "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
        },
        "held_out": _partition_report(disagreements=1, dual=4),
    }
    out = summarize_disagreement_outlook(art)
    assert out["partitions"]["tuned"]["disagreement_rate"] == 0.8
    assert out["partitions"]["tuned"]["disagreements"] == 8
    assert out["disagreement_rate"] == round(9 / 14, 3)
    assert out["verdict"] == "unstable"


def test_generalization_overall_sums_partitions_when_no_top_level_telemetry():
    art = {
        "generalization_gap": 0.0,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": _partition_report(disagreements=2, dual=4),
    }
    out = summarize_disagreement_outlook(art)
    assert out["kind"] == "generalization"
    assert out["dual_order_tasks"] == 8
    assert out["disagreements"] == 3
    assert out["disagreement_rate"] == 0.375
    assert out["verdict"] == "unstable"
    assert out["partitions"]["tuned"]["disagreement_rate"] == 0.25
    assert out["partitions"]["held_out"]["disagreement_rate"] == 0.5


def test_generalization_missing_partition_telemetry_yields_none_overall():
    art = {
        "generalization_gap": None,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": {},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


def test_generalization_incoherent_partition_yields_none_overall():
    # A partition whose disagreements exceed its dual_order_tasks is impossible telemetry; it must
    # not be pooled into a fabricated >100% overall rate. Mirrors regression._disagreement (#1283).
    art = {
        "generalization_gap": 0.1,
        "tuned": {"judge_order_stats": {"dual_order_tasks": 5, "disagree": 10, "disagreement_rate": 0.5}},
        "held_out": {"judge_order_stats": {"dual_order_tasks": 5, "disagree": 1}},
    }
    out = summarize_disagreement_outlook(art)
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None
    assert out["partitions"]["tuned"]["disagreement_rate"] is None
    assert out["partitions"]["held_out"]["disagreement_rate"] == 0.2


def test_incoherent_disagree_exceeds_dual_yields_none_slice():
    # disagree > dual_order_tasks is impossible; the slice reports no usable telemetry rather than
    # a fabricated rate, even when a stale disagreement_rate is stored alongside.
    out = summarize_disagreement_outlook(
        {"judge_order_stats": {"dual_order_tasks": 5, "disagree": 10, "disagreement_rate": 0.5}})
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


def test_generalization_headline_includes_partition_rates():
    art = {
        "generalization_gap": 0.0,
        "tuned": _partition_report(disagreements=1, dual=4),
        "held_out": _partition_report(disagreements=0, dual=4),
    }
    line = disagreement_outlook_headline(summarize_disagreement_outlook(art))
    assert "tuned 25.0%" in line
    assert "held-out 0.0%" in line


def test_missing_telemetry_yields_none_verdict():
    out = summarize_disagreement_outlook({"composite_mean": 0.5})
    assert out["verdict"] is None
    assert out["disagreement_rate"] is None


def test_nan_disagreement_rate_yields_none_verdict():
    out = summarize_disagreement_outlook(_run(float("nan"), 2))
    assert out["disagreement_rate"] is None
    assert out["verdict"] is None


def test_inf_disagreement_rate_yields_none_verdict():
    out = summarize_disagreement_outlook(_run(float("inf"), 2))
    assert out["disagreement_rate"] is None


def test_negative_dual_order_tasks_treated_as_missing():
    out = summarize_disagreement_outlook(_run(0.1, -1))
    assert out["dual_order_tasks"] is None


def test_non_int_dual_order_tasks_treated_as_missing():
    art = _run(0.1, 2)
    art["judge_report"]["dual_order_tasks"] = 2.5
    out = summarize_disagreement_outlook(art)
    assert out["dual_order_tasks"] is None


def test_non_dict_artifact_kind_invalid():
    out = summarize_disagreement_outlook([])
    assert out["kind"] == "invalid"


def test_headline_with_finite_rate():
    out = summarize_disagreement_outlook(_run(0.2, 3))
    line = disagreement_outlook_headline(out)
    assert "stable" in line
    assert "20.0%" in line


def test_headline_with_nan_rate_does_not_crash():
    out = summarize_disagreement_outlook(_run(float("nan"), 2))
    line = disagreement_outlook_headline(out)
    assert "n/a" in line
    assert "unknown" in line


def test_headline_with_inf_rate_does_not_crash():
    out = summarize_disagreement_outlook(_run(float("inf"), 2))
    assert "n/a" in disagreement_outlook_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(0.1, 4))
    assert cli.run([path]) == 0
    captured = capsys.readouterr()
    body = json.loads(captured.out)
    assert body["verdict"] == "stable"
    assert "disagreement outlook" in captured.err


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
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_custom_threshold_flag(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _run(0.25, 2))
    assert cli.run([path, "--stable-threshold", "0.2"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["verdict"] == "unstable"
    assert body["stable_threshold"] == 0.2


def test_cli_broken_symlink_exits_two(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    assert cli.run([str(link)]) == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and "Traceback" not in err


def test_load_artifact_broken_symlink_is_handled(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(link))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and "Traceback" not in err


def test_cli_directory_path_exits_two(tmp_path, capsys):
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert ("directory" in err or "not readable" in err) and "Traceback" not in err


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err
