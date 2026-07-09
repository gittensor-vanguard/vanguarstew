"""Tests for the candidate-vs-baseline regression gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.regression import (  # noqa: E402
    DEFAULT_MAX_COMPOSITE_DROP,
    _check_rows_list,
    check_regression,
    failed_checks,
    regression_headline,
)


def _run(composite, disagreement=None):
    art = {"composite_mean": composite, "rows": []}
    if disagreement is not None:
        art["judge_report"] = {"disagreement_rate": disagreement}
    return art


def _gen(tuned):
    return {"tuned": {"composite_mean": tuned, "scored_repos": 3},
            "held_out": {"composite_mean": 0.5, "scored_repos": 2}, "generalization_gap": 0.1}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_an_improvement_passes():
    result = check_regression(_run(0.66), _run(0.60))
    assert result["passed"] is True
    assert _names(result) == ["both_scored", "no_composite_regression", "no_judge_instability_increase"]
    assert result["composite_delta"] == 0.06


def test_a_small_drop_within_tolerance_passes():
    result = check_regression(_run(0.59), _run(0.60), max_composite_drop=0.02)
    assert result["passed"] is True
    assert result["composite_delta"] == -0.01


def test_a_drop_beyond_tolerance_is_blocked():
    result = check_regression(_run(0.55), _run(0.60), max_composite_drop=0.02)
    assert result["passed"] is False
    assert failed_checks(result) == ["no_composite_regression"]
    assert result["composite_delta"] == -0.05


def test_drop_exactly_at_tolerance_passes():
    # The bound is inclusive: a drop equal to max_composite_drop is allowed.
    assert check_regression(_run(0.58), _run(0.60), max_composite_drop=0.02)["passed"] is True
    assert check_regression(_run(0.579), _run(0.60), max_composite_drop=0.02)["passed"] is False


def test_max_composite_drop_is_configurable():
    runs = (_run(0.57), _run(0.60))                 # drop 0.03
    assert check_regression(*runs, max_composite_drop=0.05)["passed"] is True
    assert check_regression(*runs, max_composite_drop=0.02)["passed"] is False


def test_missing_composite_fails_both_scored():
    result = check_regression({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert result["candidate_composite"] is None


def test_regression_compares_generalization_tuned_scores():
    result = check_regression(_gen(0.66), _gen(0.60))
    assert result["baseline_composite"] == 0.60 and result["candidate_composite"] == 0.66
    assert result["passed"] is True


def test_rising_judge_instability_is_blocked():
    # Composite held, but the judge got much less stable -> block.
    result = check_regression(_run(0.60, disagreement=0.5), _run(0.60, disagreement=0.1),
                              max_disagreement_increase=0.1)
    assert result["passed"] is False
    assert "no_judge_instability_increase" in failed_checks(result)
    assert result["disagreement_delta"] == 0.4


def test_stale_judge_report_disagreement_rate_is_recomputed_from_stats():
    def art(rate, stats_dis):
        return {
            "composite_mean": 0.6,
            "judge_report": {"disagreement_rate": rate, "dual_order_tasks": 10},
            "judge_order_stats": {
                "dual_order_tasks": 10, "disagree": stats_dis, "agree": 2, "tie": 0,
            },
        }

    baseline = art(0.1, 1)
    candidate = art(0.05, 8)
    result = check_regression(candidate, baseline, max_disagreement_increase=0.1)
    assert result["passed"] is False
    assert result["disagreement_delta"] == 0.7
    assert "no_judge_instability_increase" in failed_checks(result)


def test_disagreement_falls_back_to_report_when_stats_absent():
    from benchmark.regression import _disagreement

    art = {"judge_report": {"disagreement_rate": 0.25, "dual_order_tasks": 4}}
    assert _disagreement(art) == 0.25


def test_judge_instability_only_compared_when_both_report_it():
    # One run judged single-order (no disagreement rate) -> the judge check passes vacuously.
    result = check_regression(_run(0.60, disagreement=0.9), _run(0.60))   # baseline has none
    trust = next(c for c in result["checks"] if c["name"] == "no_judge_instability_increase")
    assert trust["passed"] is True and "single-order" not in trust["detail"]
    assert result["disagreement_delta"] is None


def test_malformed_or_non_dict_artifacts_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_regression(bad, _run(0.6))
        assert result["passed"] is False
        assert result["checks"]
        assert result["candidate_composite"] is None


def test_headline_reports_ok_and_blocked():
    assert "OK" in regression_headline(check_regression(_run(0.65), _run(0.60)))
    blocked = regression_headline(check_regression(_run(0.4), _run(0.6)))
    assert "BLOCKED" in blocked and "no_composite_regression" in blocked
    assert regression_headline({}) == "regression: no checks evaluated"
    assert DEFAULT_MAX_COMPOSITE_DROP == 0.02


def test_disagreement_increase_exactly_at_bound_passes():
    # The judge-instability bound is inclusive: a rise equal to the limit is allowed.
    at = check_regression(_run(0.6, 0.20), _run(0.6, 0.10), max_disagreement_increase=0.1)
    assert at["passed"] is True and at["disagreement_delta"] == 0.1
    over = check_regression(_run(0.6, 0.21), _run(0.6, 0.10), max_disagreement_increase=0.1)
    assert over["passed"] is False


def test_both_a_composite_drop_and_instability_rise_each_fail():
    result = check_regression(_run(0.40, 0.6), _run(0.60, 0.1))
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"no_composite_regression", "no_judge_instability_increase"}
    assert len(result["checks"]) == 3          # every check still reported


def test_check_regression_does_not_mutate_inputs():
    baseline, candidate = _run(0.6, 0.1), _run(0.62, 0.1)
    snap_b, snap_c = copy.deepcopy(baseline), copy.deepcopy(candidate)
    check_regression(candidate, baseline)
    assert baseline == snap_b and candidate == snap_c


# --- #755: checks row sanitization for regression headlines --------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "both_scored"}, "not a list",
    ({"name": "both_scored", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "both_scored", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "both_scored", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "both_scored", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "both_scored", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "both_scored", "passed": False},
        {"name": "no_composite_regression", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": 99, "passed": False},
        {"name": "both_scored", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert _check_rows_list([{"name": "both_scored"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_regression_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert regression_headline({"checks": bad, "passed": False}) == (
            "regression: no checks evaluated"
        ), bad


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_regression_headline_survives_falsy_scalar_checks(bad):
    assert regression_headline({"checks": bad, "passed": False}) == (
        "regression: no checks evaluated"
    )


def test_regression_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "both_scored"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "both_scored", "passed": 1}],
    ):
        assert regression_headline({"checks": checks, "passed": False}) == (
            "regression: no checks evaluated"
        )


def test_regression_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "both_scored", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        line = regression_headline({"checks": checks, "passed": False})
    assert line == "regression: BLOCKED (1/1 checks failed: both_scored)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_regression_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        line = regression_headline({"checks": 42, "passed": False})
    assert line == "regression: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "both_scored"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "both_scored", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "both_scored", "passed": False},
        42,
        {"name": "no_composite_regression", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.regression"):
        assert failed_checks({"checks": checks}) == ["both_scored"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.regression", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_run(0.6)), encoding="utf-8")
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(good), str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the real OSError message, not a paraphrase: errno, the exact reason, and the path
    assert "No such file or directory" in result.stderr
    assert str(missing) in result.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_cli_reports_a_clean_error_for_an_unreadable_file(tmp_path):
    # PermissionError is a subclass of OSError, so it is already caught by the existing
    # except clause -- this proves that in practice, not just by inheritance.
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_run(0.6)), encoding="utf-8")
    unreadable = tmp_path / "unreadable.json"
    unreadable.write_text(json.dumps(_run(0.5)), encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        result = _run_cli(str(good), str(unreadable))
    finally:
        unreadable.chmod(0o644)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "Permission denied" in result.stderr
    assert str(unreadable) in result.stderr


@pytest.mark.parametrize("payload", [[1, 2, 3], "just a string", 42, 3.14, True, None])
def test_cli_reports_a_clean_error_for_every_non_object_json_shape(tmp_path, payload):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_run(0.6)), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    result = _run_cli(str(good), str(bad))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert f"artifact must be a JSON object: {bad}" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path), str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the real json.JSONDecodeError text, not a generic placeholder
    assert "Expecting property name enclosed in double quotes" in result.stderr


def test_cli_still_runs_the_real_regression_logic_for_well_formed_artifacts(tmp_path):
    baseline_art, candidate_art = _run(0.6), _run(0.62)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_art), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(candidate_art), encoding="utf-8")

    result = _run_cli(str(baseline), str(candidate))
    assert result.returncode == 0

    expected = check_regression(candidate_art, baseline_art)
    payload = json.loads(result.stdout)
    # the CLI's JSON output must match check_regression's real result exactly, not just a
    # "passed": True summary -- proving the artifacts actually flowed through the gate logic.
    assert payload == expected
    assert payload["passed"] is True
    assert payload["composite_delta"] == 0.02
    assert _names(payload) == ["both_scored", "no_composite_regression", "no_judge_instability_increase"]
    assert regression_headline(expected) in result.stderr


def test_cli_reports_blocked_for_a_genuine_regression(tmp_path):
    baseline_art, candidate_art = _run(0.60), _run(0.40)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(baseline_art), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(candidate_art), encoding="utf-8")

    result = _run_cli(str(baseline), str(candidate), "--strict")
    assert result.returncode == 1        # --strict exits 1 on a blocked gate
    assert "regression: BLOCKED" in result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert "no_composite_regression" in failed_checks(payload)


def test_disagreement_reads_partition_telemetry_from_generalization():
    from benchmark.regression import _disagreement

    gen = {
        "tuned": {
            "judge_report": {"disagreements": 2, "dual_order_tasks": 10},
            "composite_mean": 0.7,
            "scored_repos": 2,
        },
        "held_out": {
            "judge_report": {"disagreements": 1, "dual_order_tasks": 5},
            "composite_mean": 0.5,
            "scored_repos": 1,
        },
    }
    rate = _disagreement(gen)
    assert rate is not None
    assert rate == pytest.approx(3 / 15)


def test_disagreement_returns_none_when_partitions_lack_dual_order():
    from benchmark.regression import _disagreement

    gen = {
        "tuned": {"judge_report": {}, "composite_mean": 0.7, "scored_repos": 2},
        "held_out": {"judge_report": {}, "composite_mean": 0.5, "scored_repos": 1},
    }
    assert _disagreement(gen) is None


def test_generalization_partition_stats_override_stale_report_counts():
    from benchmark.regression import _disagreement

    gen = {
        "tuned": {
            "judge_report": {"disagreements": 0, "dual_order_tasks": 10},
            "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
            "composite_mean": 0.7,
            "scored_repos": 2,
        },
        "held_out": {
            "judge_report": {"disagreements": 1, "dual_order_tasks": 5},
            "composite_mean": 0.5,
            "scored_repos": 1,
        },
    }
    assert _disagreement(gen) == pytest.approx(9 / 15)
