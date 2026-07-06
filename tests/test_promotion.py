"""Tests for the challenger-promotion gate (deterministic, offline)."""

import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.promotion import (  # noqa: E402
    DEFAULT_MIN_COMPOSITE,
    check_promotion,
    failed_checks,
    promotion_headline,
)


def _result(composite=0.7, margin=2, disagreement=0.1, tally=None, error=None):
    r = {"composite_mean": composite, "judge_report": {"disagreement_rate": disagreement}}
    if margin is not None:
        r["decisive_margin"] = margin
    if tally is not None:
        r["tally"] = tally
    if error is not None:
        r["error"] = error
    return r


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_strong_run_is_promoted():
    result = check_promotion(_result(composite=0.7, margin=2, disagreement=0.1))
    assert result["passed"] is True
    assert all(c["passed"] for c in result["checks"])
    assert _names(result) == ["run_completed", "composite_floor", "beats_baseline", "judge_trustworthy"]
    assert result["composite_mean"] == 0.7 and result["decisive_margin"] == 2


def test_composite_below_floor_holds():
    result = check_promotion(_result(composite=0.4), min_composite=0.5)
    assert result["passed"] is False
    assert failed_checks(result) == ["composite_floor"]


def test_a_tie_run_does_not_beat_the_baseline():
    # A memorized-tie agent (margin 0) fails beats_baseline even with a decent composite.
    result = check_promotion(_result(composite=0.6, margin=0), min_decisive_margin=1)
    assert result["passed"] is False
    assert "beats_baseline" in failed_checks(result)


def test_decisive_margin_is_derived_from_tally_when_absent():
    # A multi-repo result has no top-level decisive_margin; derive it from the tally.
    result = check_promotion(_result(composite=0.7, margin=None,
                                     tally={"challenger": 5, "baseline": 2, "tie": 1}))
    assert result["decisive_margin"] == 3
    assert result["passed"] is True


def test_missing_margin_and_tally_fails_beats_baseline():
    result = check_promotion({"composite_mean": 0.7, "judge_report": {"disagreement_rate": 0.1}})
    assert "beats_baseline" in failed_checks(result)
    assert result["decisive_margin"] is None


def test_high_disagreement_is_not_trustworthy():
    result = check_promotion(_result(disagreement=0.8), max_disagreement=0.5)
    assert result["passed"] is False
    assert "judge_trustworthy" in failed_checks(result)


def test_single_order_run_passes_judge_trustworthy():
    # No disagreement_rate (single-order judge) -> the trust check passes (no instability signal).
    result = check_promotion(_result(disagreement=None))
    trust = next(c for c in result["checks"] if c["name"] == "judge_trustworthy")
    assert trust["passed"] is True and "single-order" in trust["detail"]


def test_an_error_run_fails_run_completed():
    result = check_promotion({"error": "no usable tasks", "tasks": 0})
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_thresholds_are_configurable():
    run = _result(composite=0.55, margin=1, disagreement=0.3)
    assert check_promotion(run, min_composite=0.5, min_decisive_margin=1, max_disagreement=0.5)["passed"] is True
    assert check_promotion(run, min_composite=0.6)["passed"] is False
    assert check_promotion(run, min_decisive_margin=2)["passed"] is False
    assert check_promotion(run, max_disagreement=0.2)["passed"] is False


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_promotion(bad)
        assert result["passed"] is False
        assert result["checks"]                       # evaluated, no crash
        assert result["composite_mean"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"composite_mean": "high", "decisive_margin": "lots",
             "judge_report": {"disagreement_rate": "some"}}
    result = check_promotion(weird)
    assert result["passed"] is False
    assert {"composite_floor", "beats_baseline", "judge_trustworthy"} <= set(failed_checks(result))


def test_headline_reports_promote_and_hold():
    assert "PROMOTE" in promotion_headline(check_promotion(_result()))
    hold = promotion_headline(check_promotion(_result(composite=0.1)))
    assert "HOLD" in hold and "composite_floor" in hold
    assert promotion_headline({}) == "promotion: no checks evaluated"
    assert DEFAULT_MIN_COMPOSITE == 0.5


def test_every_check_reported_even_when_several_fail():
    result = check_promotion({"error": "x", "composite_mean": 0.1, "decisive_margin": -3,
                              "judge_report": {"disagreement_rate": 0.9}})
    assert len(result["checks"]) == 4
    assert set(failed_checks(result)) == {
        "run_completed", "composite_floor", "beats_baseline", "judge_trustworthy",
    }


def test_check_promotion_does_not_mutate_the_result():
    run = _result()
    snapshot = copy.deepcopy(run)
    check_promotion(run)
    assert run == snapshot


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.promotion", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_still_reports_promote_for_a_well_formed_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_result(composite=0.7, margin=2, disagreement=0.1)), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert "PROMOTE" in result.stderr
    assert json.loads(result.stdout)["passed"] is True
