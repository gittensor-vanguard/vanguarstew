"""Tests for the N-way score trend / regression analysis (deterministic, offline)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.trend import (  # noqa: E402
    _trend_regressions,
    _trend_series,
    headline_score,
    trend,
    trend_headline,
)


def _single(score):
    return {"composite_mean": score, "composite_parts": {"judge_mean": score}}


def _gen(tuned_score):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


def test_headline_score_reads_top_level_and_generalization_tuned():
    assert headline_score(_single(0.62)) == 0.62
    assert headline_score({"per_repo": [], "composite_mean": 0.4}) == 0.4   # multi-repo
    assert headline_score(_gen(0.71)) == 0.71                               # tuned partition
    assert headline_score({"error": "no tasks"}) is None                    # no score
    assert headline_score("not a dict") is None                            # non-dict, no crash
    assert headline_score({"composite_mean": "bad"}) is None                # non-numeric


def test_headline_score_treats_unscored_tuned_partition_as_unscored():
    # A tuned partition that scored nothing (scored_repos: 0) reports a placeholder
    # composite_mean of 0.0 — a transient/infra outcome, not a real zero. It must read as None,
    # so --fail-on-regression doesn't raise a false alarm on an infra hiccup.
    unscored = {
        "tuned": {"error": "no tuned repos to replay", "scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"composite_mean": 0.56, "scored_repos": 2},
        "generalization_gap": None,
    }
    assert headline_score(unscored) is None
    # The infra hiccup is skipped, so a healthy run before and after is NOT a 0.62 -> 0.0 -> 0.63
    # crash-and-recover; the two real scores compare directly with no spurious regression.
    out = trend([("run1", _gen(0.62)), ("run2", unscored), ("run3", _gen(0.63))])
    assert [p["composite_mean"] for p in out["points"]] == [0.62, None, 0.63]
    assert out["regressions"] == []


def test_headline_score_treats_unscored_multi_repo_as_unscored():
    # A multi-repo run where every repo was too small/unreachable reports scored_repos: 0 with a
    # placeholder composite_mean of 0.0 — nothing scored, not a real zero. It must read as None.
    unscored = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "per_repo": [{"repo": "a", "error": "bad path", "tasks": 0}],
    }
    assert headline_score(unscored) is None
    # A scored multi-repo run is unaffected; a single-repo artifact (no scored_repos key) keeps its score.
    assert headline_score({"repos": 2, "scored_repos": 2, "composite_mean": 0.62}) == 0.62
    assert headline_score(_single(0.0)) == 0.0
    # A nothing-scored run between two healthy ones is skipped, so no spurious regression is flagged.
    out = trend([("run1", {"scored_repos": 2, "composite_mean": 0.62}),
                 ("run2", unscored),
                 ("run3", {"scored_repos": 2, "composite_mean": 0.63})])
    assert [p["composite_mean"] for p in out["points"]] == [0.62, None, 0.63]
    assert out["regressions"] == []


def test_trend_computes_points_deltas_and_overall_change():
    series = [("r1", _single(0.50)), ("r2", _single(0.55)), ("r3", _single(0.53))]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.50, 0.55, 0.53]
    assert out["points"][0]["delta"] is None            # first scored point has no delta
    assert out["points"][1]["delta"] == 0.05
    assert out["points"][2]["delta"] == -0.02
    assert out["first"] == 0.50 and out["last"] == 0.53
    assert out["change"] == 0.03
    assert out["min"] == 0.50 and out["max"] == 0.55
    assert out["scored"] == 3 and out["total"] == 3


def test_trend_flags_only_drops_beyond_the_threshold():
    # 0.60 -> 0.61 (up, no reg) -> 0.50 (drop 0.11 > 0.02, reg) -> 0.495 (drop 0.005 < 0.02, no reg)
    series = [("a", _single(0.60)), ("b", _single(0.61)), ("c", _single(0.50)), ("d", _single(0.495))]
    out = trend(series)
    assert [r["from_label"] for r in out["regressions"]] == ["b"]
    assert out["regressions"][0] == {"from_label": "b", "to_label": "c", "drop": 0.11}


def test_trend_threshold_is_configurable():
    series = [("a", _single(0.60)), ("b", _single(0.57))]   # drop 0.03
    assert trend(series, regression_threshold=0.02)["regressions"]      # 0.03 > 0.02 -> flagged
    assert not trend(series, regression_threshold=0.05)["regressions"]  # 0.03 < 0.05 -> not


def test_trend_skips_unscored_points_in_delta_and_regression_math():
    # The middle artifact has no score; deltas bridge the surrounding scored points, and its own
    # delta is None. 0.60 -> (skip) -> 0.50 is still a regression of 0.10.
    series = [("a", _single(0.60)), ("b", {"error": "no tasks"}), ("c", _single(0.50))]
    out = trend(series)
    assert out["points"][1]["composite_mean"] is None
    assert out["points"][1]["delta"] is None
    assert out["points"][2]["delta"] == -0.10          # bridges to the last scored point
    assert out["scored"] == 2 and out["total"] == 3
    assert [r["from_label"] for r in out["regressions"]] == ["a"]   # a -> c drop 0.10


def test_trend_empty_and_all_unscored_series():
    empty = trend([])
    assert empty["scored"] == 0 and empty["first"] is None and empty["regressions"] == []
    allbad = trend([("a", {"error": "x"}), ("b", "not-a-dict")])
    assert allbad["scored"] == 0 and allbad["change"] is None


# --- #528: a non-list series must not abort trend ------------------------------------

_MALFORMED_SERIES = [42, 3.14, True, {"label": "run1"}, "not a list"]


def test_trend_series_accepts_only_real_lists():
    rows = [("run1", {"composite_mean": 0.5})]
    for bad in _MALFORMED_SERIES:
        assert _trend_series(bad) == [], bad
    assert _trend_series(rows) == rows
    assert _trend_series(None) == []


def test_trend_survives_non_list_series():
    for bad in _MALFORMED_SERIES:
        out = trend(bad)
        assert out["scored"] == 0 and out["total"] == 0 and out["regressions"] == [], bad


def test_trend_logs_warning_for_non_list_series(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        out = trend(42)
    assert out["scored"] == 0
    assert any("series is int" in r.message for r in caplog.records)


def test_trend_headline_summarizes_direction_and_regressions():
    up = trend([("a", _single(0.50)), ("b", _single(0.60))])
    assert "up +0.100" in trend_headline(up) and "0 regression" in trend_headline(up)
    down = trend([("a", _single(0.60)), ("b", _single(0.50))])
    assert "down -0.100" in trend_headline(down) and "1 regression" in trend_headline(down)
    assert trend_headline({}) == "trend: no scored artifacts"


# --- #569: non-list regressions must not abort trend_headline ----------------------

_MALFORMED_REGRESSION_LISTS = [42, 3.14, True, {"from_label": "a"}, "not a list"]


def test_trend_regressions_accepts_only_real_lists():
    rows = [{"from_label": "a", "to_label": "b", "drop": 0.1}]
    for bad in _MALFORMED_REGRESSION_LISTS:
        assert _trend_regressions(bad) == [], bad
    assert _trend_regressions(rows) == rows
    assert _trend_regressions(None) == []


def test_trend_headline_survives_non_list_regressions():
    base = {"scored": 2, "first": 0.5, "last": 0.6, "change": 0.1}
    for bad in _MALFORMED_REGRESSION_LISTS:
        line = trend_headline({**base, "regressions": bad})
        assert "0 regression" in line, bad


def test_trend_headline_logs_warning_for_non_list_regressions(caplog):
    import logging

    summary = {"scored": 2, "first": 0.5, "last": 0.6, "change": 0.1, "regressions": 42}
    with caplog.at_level(logging.WARNING, logger="benchmark.trend"):
        line = trend_headline(summary)
    assert "0 regression" in line
    assert any("regressions is int" in r.message for r in caplog.records)


def test_trend_does_not_mutate_inputs():
    import copy
    series = [("a", _single(0.5)), ("b", _gen(0.6))]
    snapshot = copy.deepcopy(series)
    trend(series)
    assert series == snapshot


def test_trend_over_a_generalization_series_uses_tuned_score():
    # A series of --generalization artifacts trends on each one's tuned composite_mean.
    out = trend([("q1", _gen(0.60)), ("q2", _gen(0.64)), ("q3", _gen(0.58))])
    assert [p["composite_mean"] for p in out["points"]] == [0.60, 0.64, 0.58]
    assert out["change"] == -0.02
    assert [r["from_label"] for r in out["regressions"]] == ["q2"]     # 0.64 -> 0.58 drop 0.06


def test_trend_drop_exactly_at_threshold_is_not_a_regression():
    # The threshold is strict (> not >=): a drop equal to it is treated as noise, not a slide.
    out = trend([("a", _single(0.60)), ("b", _single(0.58))], regression_threshold=0.02)
    assert out["regressions"] == []


def test_trend_single_scored_point_has_no_delta_or_regression():
    out = trend([("only", _single(0.5))])
    assert out["scored"] == 1
    assert out["points"][0]["delta"] is None
    assert out["change"] == 0.0            # first == last
    assert out["regressions"] == []


def test_trend_mixes_single_multi_and_generalization_artifacts():
    series = [
        ("single", _single(0.50)),
        ("multi", {"per_repo": [], "composite_mean": 0.55}),
        ("gen", _gen(0.40)),
    ]
    out = trend(series)
    assert [p["composite_mean"] for p in out["points"]] == [0.50, 0.55, 0.40]
    assert out["min"] == 0.40 and out["max"] == 0.55
    assert [r["to_label"] for r in out["regressions"]] == ["gen"]      # 0.55 -> 0.40


# --- CLI entry point: clean errors instead of tracebacks (#641) ---------------------------


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.trend", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _run_main_in_process(monkeypatch, argv):
    import scripts.trend as trend_cli

    monkeypatch.setattr(sys, "argv", ["scripts.trend", *argv])
    with pytest.raises(SystemExit) as excinfo:
        trend_cli.main()
    return excinfo.value.code


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    good = _write(tmp_path / "good.json", _single(0.5))
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(good, str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the FileNotFoundError message itself, naming the offending path
    assert "No such file or directory" in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    good = _write(tmp_path / "good.json", _single(0.5))
    bad = _write(tmp_path / "bad.json", [1, 2, 3])
    result = _run_cli(good, bad)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # load_artifact's ValueError message, naming the offending path
    assert "must be a JSON object" in result.stderr
    assert bad in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    good = _write(tmp_path / "good.json", _single(0.5))
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(good, str(invalid))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the JSONDecodeError message with its parse position
    assert "Expecting property name enclosed in double quotes" in result.stderr
    assert "line 1" in result.stderr


def test_cli_reports_a_clean_error_for_a_directory_path(tmp_path):
    # IsADirectoryError is an OSError; end-to-end proof the guard covers the family even
    # when the suite runs as root (a chmod-000 fixture would be readable to root).
    good = _write(tmp_path / "good.json", _single(0.5))
    unreadable = tmp_path / "a-directory"
    unreadable.mkdir()
    result = _run_cli(good, str(unreadable))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "Is a directory" in result.stderr
    assert str(unreadable) in result.stderr


def test_cli_reports_a_clean_error_for_a_permission_denied_file(tmp_path, monkeypatch, capsys):
    # In-process, so it holds under any uid (root reads chmod-000 files, so a filesystem
    # fixture cannot force EACCES deterministically): PermissionError must surface as the
    # one-line OSError message and a clean exit 1, never a traceback.
    import scripts.trend as trend_cli

    good = _write(tmp_path / "good.json", _single(0.5))
    denied = str(tmp_path / "denied.json")
    real_load = trend_cli.load_artifact

    def _load(path):
        if path == denied:
            raise PermissionError(13, "Permission denied", denied)
        return real_load(path)

    monkeypatch.setattr(trend_cli, "load_artifact", _load)
    code = _run_main_in_process(monkeypatch, [good, denied])
    assert code == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err
    assert denied in err


def test_cli_reports_a_clean_error_when_analysis_itself_fails(tmp_path, monkeypatch, capsys):
    # The guard is not just around loading: if trend analysis blows up on artifact content,
    # the CLI must still exit 1 with a one-line error instead of a traceback.
    import scripts.trend as trend_cli

    good = _write(tmp_path / "good.json", _single(0.5))

    def _boom(series, regression_threshold):
        raise TypeError("unhashable artifact content")

    monkeypatch.setattr(trend_cli, "trend", _boom)
    code = _run_main_in_process(monkeypatch, [good])
    assert code == 1
    err = capsys.readouterr().err
    assert "cannot analyze artifacts" in err
    assert "unhashable artifact content" in err


def test_cli_still_trends_well_formed_artifacts(tmp_path):
    a = _write(tmp_path / "a.json", _single(0.5))
    b = _write(tmp_path / "b.json", _single(0.7))
    result = _run_cli(a, b)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    summary = json.loads(result.stdout)
    assert [p["composite_mean"] for p in summary["points"]] == [0.5, 0.7]


def test_cli_fail_on_regression_exit_comes_from_the_gating_branch(tmp_path):
    # The error guards must not swallow or fake the CI gating path. Prove the exit 1
    # originates from the gating branch: the full analysis completed (headline + REGRESSION
    # row on stderr, parseable summary on stdout with the regression recorded), the gating
    # message is present, and no loader/analysis error message appears.
    a = _write(tmp_path / "a.json", _single(0.7))
    b = _write(tmp_path / "b.json", _single(0.4))
    result = _run_cli(a, b, "--fail-on-regression")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "REGRESSION a.json -> b.json" in result.stderr
    assert "trend: 1 regression(s) exceed the threshold" in result.stderr
    summary = json.loads(result.stdout)
    assert len(summary["regressions"]) == 1
    assert "cannot analyze artifacts" not in result.stderr
    assert "No such file or directory" not in result.stderr


def test_cli_without_gating_flag_exits_zero_despite_regressions(tmp_path):
    # Same regressing series, no --fail-on-regression: the run reports and exits 0,
    # confirming exit 1 above is the flag's doing rather than any error path.
    a = _write(tmp_path / "a.json", _single(0.7))
    b = _write(tmp_path / "b.json", _single(0.4))
    result = _run_cli(a, b)
    assert result.returncode == 0
    assert "REGRESSION a.json -> b.json" in result.stderr
