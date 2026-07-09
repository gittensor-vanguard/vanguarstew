"""Tests for the repeated-run stability (repeatability) gate (deterministic, offline)."""

import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repeatability import (  # noqa: E402
    DEFAULT_MAX_CV,
    _repeatability_artifacts,
    assess_repeatability,
    repeatability_headline,
)


def _run(score):
    return {"composite_mean": score, "rows": []}


def _gen(tuned_score):
    return {
        "tuned": {"composite_mean": tuned_score, "scored_repos": 3},
        "held_out": {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


def test_tight_repeats_are_stable():
    result = assess_repeatability([_run(0.60), _run(0.61), _run(0.59)], max_cv=0.05)
    assert result["stable"] is True
    assert result["runs"] == 3
    assert result["mean"] == 0.6
    assert result["min"] == 0.59 and result["max"] == 0.61
    assert result["range"] == 0.02
    assert 0 < result["cv"] <= 0.05
    assert result["reason"] == ""


def test_wide_spread_is_unstable_with_a_reason():
    result = assess_repeatability([_run(0.40), _run(0.60), _run(0.80)], max_cv=0.05)
    assert result["stable"] is False
    assert "cv" in result["reason"] and "exceeds max_cv" in result["reason"]
    assert result["cv"] > 0.05


def test_identical_runs_have_zero_cv_and_are_stable():
    result = assess_repeatability([_run(0.5), _run(0.5), _run(0.5)])
    assert result["cv"] == 0.0 and result["stddev"] == 0.0
    assert result["stable"] is True


def test_zero_mean_with_spread_is_unstable_not_a_crash():
    # A zero mean with nonzero spread cannot be normalized into a CV (division by zero); it must
    # be reported as unstable, not crash. Reachable via a (defensively handled) negative score.
    result = assess_repeatability([_run(-0.1), _run(0.1)])
    assert result["mean"] == 0.0 and result["stddev"] > 0
    assert result["cv"] is None
    assert result["stable"] is False
    assert "undefined" in result["reason"]


def test_all_zero_runs_are_perfectly_stable():
    result = assess_repeatability([_run(0.0), _run(0.0)])
    assert result["stddev"] == 0.0 and result["cv"] == 0.0
    assert result["stable"] is True


def test_max_cv_is_configurable():
    runs = [_run(0.50), _run(0.55)]                 # cv ~= 0.067
    assert assess_repeatability(runs, max_cv=0.02)["stable"] is False
    assert assess_repeatability(runs, max_cv=0.10)["stable"] is True


def test_insufficient_runs_is_inconclusive():
    result = assess_repeatability([_run(0.6)], min_runs=2)
    assert result["stable"] is False
    assert result["runs"] == 1
    assert "insufficient runs" in result["reason"]
    assert result["mean"] is None
    assert assess_repeatability([], min_runs=2)["runs"] == 0


def test_unscored_runs_are_skipped_not_counted():
    result = assess_repeatability([_run(0.6), {"error": "no tasks"}, _run(0.62), "not-a-dict"])
    assert result["runs"] == 2                       # only the two scored runs count
    assert result["scores"] == [0.6, 0.62]


def test_unscored_multi_repo_run_is_skipped_not_folded_into_spread():
    # A repeat where every repo was too small reports scored_repos: 0 with a placeholder 0.0;
    # folding it into the spread would fabricate a false UNSTABLE verdict, so it must be skipped.
    empty_run = {"repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
                 "per_repo": [{"repo": "a", "error": "bad path", "tasks": 0}]}
    result = assess_repeatability([_run(0.60), empty_run, _run(0.61)])
    assert result["runs"] == 2                       # only the two scored repeats count
    assert result["scores"] == [0.6, 0.61]
    assert result["stable"] is True


def test_repeatability_reads_generalization_tuned_score():
    result = assess_repeatability([_gen(0.70), _gen(0.71), _gen(0.69)])
    assert result["scores"] == [0.7, 0.71, 0.69]
    assert result["stable"] is True


def test_headline_reports_stable_unstable_and_inconclusive():
    stable = assess_repeatability([_run(0.6), _run(0.61)])
    assert "STABLE over 2 runs" in repeatability_headline(stable)
    unstable = assess_repeatability([_run(0.4), _run(0.8)])
    assert "UNSTABLE" in repeatability_headline(unstable)
    assert "inconclusive" in repeatability_headline(assess_repeatability([_run(0.6)]))
    assert repeatability_headline({}) == "repeatability: no scored runs"
    assert DEFAULT_MAX_CV == 0.05


def test_cv_uses_sample_standard_deviation():
    # The CV of a sample of repeated runs uses the sample (Bessel-corrected) standard deviation,
    # so run-to-run spread is not underestimated. Population stddev (pstdev) would give sd=0.04,
    # cv=0.04 <= 0.05 and call this STABLE; the sample stddev is 0.057, cv=0.057 > 0.05 -> UNSTABLE.
    result = assess_repeatability([_run(0.96), _run(1.04)], max_cv=0.05)
    assert result["stddev"] == 0.057
    assert result["cv"] == 0.057
    assert result["stable"] is False
    assert "exceeds max_cv" in result["reason"]


def test_cv_boundary_is_inclusive():
    # stable requires cv <= max_cv; a cv exactly at the bound passes.
    runs = [_run(0.50), _run(0.55)]                 # sd 0.035, mean 0.525, cv ~= 0.067
    result = assess_repeatability(runs)
    assert assess_repeatability(runs, max_cv=result["cv"])["stable"] is True
    assert assess_repeatability(runs, max_cv=result["cv"] - 0.001)["stable"] is False


def test_min_runs_is_configurable():
    runs = [_run(0.6), _run(0.61)]
    assert assess_repeatability(runs, min_runs=2)["runs"] == 2
    assert assess_repeatability(runs, min_runs=3)["stable"] is False   # 2 < 3 -> inconclusive


def test_a_realistic_five_repeat_acceptance_run():
    # Five tight repeats of a generalization acceptance run read stable and report the spread.
    result = assess_repeatability([_gen(s) for s in (0.61, 0.60, 0.62, 0.61, 0.60)], max_cv=0.05)
    assert result["runs"] == 5
    assert result["stable"] is True
    assert result["min"] == 0.6 and result["max"] == 0.62
    assert result["range"] == 0.02
    assert "STABLE over 5 runs" in repeatability_headline(result)


def test_assess_does_not_mutate_inputs():
    artifacts = [_run(0.6), _gen(0.7)]
    snapshot = copy.deepcopy(artifacts)
    assess_repeatability(artifacts)
    assert artifacts == snapshot


# --- non-list artifacts must not abort assess_repeatability -------------------------

_MALFORMED_ARTIFACTS = [42, 3.14, True, {"composite_mean": 0.5}, "not a list"]


def test_repeatability_artifacts_accepts_only_real_lists():
    rows = [_run(0.6)]
    for bad in _MALFORMED_ARTIFACTS:
        assert _repeatability_artifacts(bad) == [], bad
    assert _repeatability_artifacts(rows) == rows
    assert _repeatability_artifacts(None) == []


def test_assess_repeatability_survives_non_list_artifacts():
    for bad in _MALFORMED_ARTIFACTS:
        result = assess_repeatability(bad, min_runs=2)
        assert result["runs"] == 0 and result["stable"] is False, bad
        assert "insufficient runs" in result["reason"], bad


def test_assess_repeatability_logs_warning_for_non_list_artifacts(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.repeatability"):
        result = assess_repeatability(42, min_runs=2)
    assert result["runs"] == 0
    assert any("artifacts is int" in r.message for r in caplog.records)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.repeatability", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_run(0.6)), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(good), str(bad))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_still_reports_stable_for_well_formed_artifacts(tmp_path):
    paths = []
    for i, score in enumerate((0.60, 0.61, 0.59)):
        p = tmp_path / f"run{i}.json"
        p.write_text(json.dumps(_run(score)), encoding="utf-8")
        paths.append(str(p))
    result = _run_cli(*paths, "--max-cv", "0.05")
    assert result.returncode == 0
    assert "STABLE" in result.stderr
    assert json.loads(result.stdout)["stable"] is True
