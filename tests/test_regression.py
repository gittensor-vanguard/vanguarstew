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


# --- #1257: a repo that failed to clone/freeze is recorded inside per_repo, not as a run error --
# run_multi_replay does not abort on a bad repo: it stores {"error": ..., "tasks": 0} in
# per_repo[i] and counts it in `skipped`, so headline_score reads a composite averaged over a
# partial, biased subset. both_scored must scan the compared (headline) partition of BOTH runs —
# a dirty candidate is not safe to accept, and a dirty baseline makes the comparison meaningless —
# via the same acceptance._partition_error check_improvement (#1328) and check_promotion (#1254)
# reuse. The failure detail names only the erroring side, never the artifact internals.


def _multi(composite=0.66, per_repo=None, **overrides):
    run = {"composite_mean": composite, "scored_repos": 2, "repos": 3, "skipped": 1}
    if per_repo is not None:
        run["per_repo"] = per_repo
    run.update(overrides)
    return run


def _both_detail(result):
    return next(c["detail"] for c in result["checks"] if c["name"] == "both_scored")


_BAD_ROW = {"repo": "bad-clone", "error": "failed to clone repo-set source 'owner/missing'", "tasks": 0}
_CLEAN_ROWS = [{"repo": "good-a", "composite_mean": 0.70, "tasks": 4},
               {"repo": "good-b", "composite_mean": 0.62, "tasks": 3}]


# --- direct unit tests for the new helper _headline_source ------------------------------------


def test_headline_source_selects_the_partition_headline_score_reads():
    from benchmark.regression import _headline_source
    from benchmark.trend import headline_score

    tuned = {"composite_mean": 0.7}
    gen = {"tuned": tuned, "held_out": {"composite_mean": 0.5}}
    assert _headline_source(gen) is tuned                                  # real generalization pair
    for flat in (
        {"tuned": tuned},                                                  # held_out absent
        {"tuned": tuned, "held_out": None},                                # held_out non-dict
        {"tuned": "oops", "held_out": {"composite_mean": 0.5}},            # tuned non-dict
        {"composite_mean": 0.6},                                           # plain artifact
        {},                                                                # empty dict, no keys
    ):
        assert _headline_source(flat) is flat
        # the scan and the score always read the same partition
        assert headline_score(flat) == _headline_source(flat).get("composite_mean")


def test_headline_source_requires_both_partitions_to_be_dicts():
    from benchmark.regression import _headline_source

    # only when BOTH tuned and held_out are dicts is the artifact a generalization pair
    assert _headline_source({"tuned": {}, "held_out": {}}) == {}
    for not_gen in ({"held_out": {}}, {"tuned": {}}, {"tuned": [], "held_out": {}},
                    {"tuned": {}, "held_out": 5}):
        assert _headline_source(not_gen) is not_gen


# --- direct unit tests for the new helper _artifact_error (returns a plain bool) ---------------


def test_artifact_error_returns_bool_for_every_source():
    from benchmark.regression import _artifact_error

    # clean shapes -> False
    for clean in (None, "not a dict", 42, [1, 2], {}, _multi(), _multi(per_repo=[]),
                  _multi(per_repo=list(_CLEAN_ROWS))):
        assert _artifact_error(clean) is False, clean
    # dirty shapes -> True, always a bool (never the underlying error value)
    for dirty in ({"error": "boom"}, _multi(per_repo=[_BAD_ROW]),
                  {"tuned": {"per_repo": [_BAD_ROW]}, "held_out": {"composite_mean": 0.5}}):
        result = _artifact_error(dirty)
        assert result is True, dirty


def test_artifact_error_handles_missing_keys_without_raising():
    from benchmark.regression import _artifact_error

    # no per_repo, no composite_mean, no tuned/held_out — none of these raise KeyError
    assert _artifact_error({}) is False
    assert _artifact_error({"scored_repos": 2}) is False
    assert _artifact_error({"tuned": {"composite_mean": 0.6}}) is False   # lone tuned, no held_out


def test_artifact_error_handles_mixed_error_types_consistently():
    from benchmark.regression import _artifact_error

    # per_repo[i].error may be a string, a non-empty dict, or another truthy object -> all dirty
    assert _artifact_error(_multi(per_repo=[{"repo": "b", "tasks": 0, "error": "clone failed"}])) is True
    assert _artifact_error(_multi(per_repo=[{"repo": "b", "tasks": 0, "error": {"code": 128}}])) is True
    assert _artifact_error(_multi(per_repo=[{"repo": "b", "tasks": 0, "error": ["fatal"]}])) is True
    # a bare non-empty string row is a corrupt entry -> dirty (fails closed)
    assert _artifact_error(_multi(per_repo=["fatal: not a git repository"])) is True
    # falsy error values ("", 0, None, False) and blank string rows are NOT errors
    for falsy in ("", 0, None, False):
        assert _artifact_error(_multi(per_repo=[{"repo": "a", "tasks": 4, "error": falsy}])) is False, falsy
    assert _artifact_error(_multi(per_repo=["", "   "])) is False
    # non-dict / non-string rows and a non-list per_repo are ignored, never raise
    assert _artifact_error(_multi(per_repo=[42, None, [1, 2]])) is False
    assert _artifact_error(_multi(per_repo="oops")) is False


def test_artifact_error_scans_only_the_headline_partition():
    from benchmark.regression import _artifact_error

    # a per-repo error confined to held_out is not read by headline_score -> not an error here
    gen = _gen(0.66)
    gen["held_out"] = {"composite_mean": 0.5, "scored_repos": 1, "per_repo": [_BAD_ROW]}
    assert _artifact_error(gen) is False
    # the same error in the compared tuned partition IS an error
    gen["tuned"]["per_repo"] = [_BAD_ROW]
    assert _artifact_error(gen) is True


# --- both_scored logic: assert the exact pass/fail flips --------------------------------------


def test_issue_1257_repro_candidate_per_repo_clone_error_is_blocked():
    # The exact artifacts from #1257: the candidate "improved" to 0.66 but one repo never cloned.
    # Before the fix both_scored and no_composite_regression passed on the partial composite.
    baseline = {"composite_mean": 0.60, "scored_repos": 3, "repos": 3}
    candidate = _multi(per_repo=_CLEAN_ROWS + [_BAD_ROW])
    result = check_regression(candidate, baseline)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"both_scored", "no_composite_regression"}
    assert result["composite_delta"] is None       # a partial composite is not a comparable delta


def test_both_scored_flips_false_only_because_of_the_error():
    # Control + flip on the SAME scores: identical composites, the only difference is a per-repo
    # error -> both_scored flips True to False, proving the error (not the score) drives it.
    clean = check_regression(_multi(per_repo=list(_CLEAN_ROWS), scored_repos=2, repos=2, skipped=0),
                             _multi(composite=0.60))
    assert clean["passed"] is True
    dirty = check_regression(_multi(per_repo=_CLEAN_ROWS + [_BAD_ROW]), _multi(composite=0.60))
    assert dirty["passed"] is False
    assert "both_scored" in failed_checks(dirty)


def test_candidate_per_repo_error_fails_both_scored():
    result = check_regression(_multi(per_repo=[_BAD_ROW]), _multi(composite=0.60))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert _both_detail(result) == "candidate run has a partition or per-repo error"


def test_baseline_per_repo_error_blocks_a_clean_candidate():
    # The gate compares against the baseline; if the baseline itself was computed over a partial
    # subset, the comparison is meaningless — a candidate must not pass against a dirty floor.
    baseline = _multi(composite=0.60, per_repo=_CLEAN_ROWS + [_BAD_ROW])
    candidate = _multi(per_repo=list(_CLEAN_ROWS), scored_repos=2, repos=2, skipped=0)
    result = check_regression(candidate, baseline)
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    assert _both_detail(result) == "baseline run has a partition or per-repo error"


def test_both_runs_dirty_names_both_sides():
    result = check_regression(_multi(per_repo=[_BAD_ROW]), _multi(composite=0.60, per_repo=[_BAD_ROW]))
    assert result["passed"] is False
    assert _both_detail(result) == "both runs have a partition or per-repo error"


def test_run_level_error_also_fails_both_scored():
    # A top-level error (whole-run failure), not just per-repo, blocks the gate on either side.
    assert check_regression(_multi(error="run aborted"), _multi(composite=0.60))["passed"] is False
    assert check_regression(_multi(), _multi(composite=0.60, error="run aborted"))["passed"] is False


# --- detail sanitization: the message must never expose artifact internals (#1257 review) ------


def test_both_scored_detail_never_exposes_internal_error_data():
    # The per-repo error carries internal data (a dict with a stack trace / path). The detail must
    # name only the side, never echo the raw error object or per_repo row.
    leaky_row = {"repo": "b", "tasks": 0,
                 "error": {"stacktrace": "INTERNAL /etc/passwd:42", "returncode": 128}}
    result = check_regression(_multi(per_repo=[leaky_row]), _multi(composite=0.60))
    detail = _both_detail(result)
    assert detail == "candidate run has a partition or per-repo error"
    for leaked in ("stacktrace", "passwd", "returncode", "128", "INTERNAL", "{", "}"):
        assert leaked not in detail
    # a string error is not echoed verbatim either
    result2 = check_regression(_multi(per_repo=[_BAD_ROW]), _multi(composite=0.60))
    assert "owner/missing" not in _both_detail(result2)


# --- generalization partitions -----------------------------------------------------------------


def test_generalization_candidate_tuned_per_repo_error_is_blocked():
    candidate = _gen(0.66)
    candidate["tuned"]["per_repo"] = [_CLEAN_ROWS[0], _BAD_ROW]
    result = check_regression(candidate, _gen(0.60))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_generalization_baseline_tuned_per_repo_error_is_blocked():
    baseline = _gen(0.60)
    baseline["tuned"]["per_repo"] = [_BAD_ROW]
    result = check_regression(_gen(0.66), baseline)
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_generalization_held_out_per_repo_error_is_ignored_on_both_sides():
    # Only the compared (tuned) partition is scanned — headline_score never reads held_out, so a
    # per-repo error confined there does not block (same scope as check_improvement, #1328).
    baseline, candidate = _gen(0.60), _gen(0.66)
    baseline["held_out"]["per_repo"] = [_BAD_ROW]
    candidate["held_out"]["per_repo"] = [_BAD_ROW]
    result = check_regression(candidate, baseline)
    assert result["passed"] is True
    assert failed_checks(result) == []


def test_missing_held_out_is_scanned_at_the_top_level():
    # An artifact with a lone tuned block and no held_out key is NOT a generalization pair:
    # headline_score reads its top level, so the error scan must too — a per-repo error hidden in
    # the ignored tuned block does not block, while a top-level per-repo error does.
    lone_tuned = {"tuned": {"composite_mean": 0.9, "per_repo": [_BAD_ROW]},
                  "composite_mean": 0.66, "per_repo": list(_CLEAN_ROWS)}
    assert check_regression(lone_tuned, _multi(composite=0.60))["passed"] is True
    dirty_top = dict(lone_tuned, per_repo=[_BAD_ROW])
    result = check_regression(dirty_top, _multi(composite=0.60))
    assert result["passed"] is False and "both_scored" in failed_checks(result)


# --- robustness: missing keys, non-dict artifacts, clean controls ------------------------------


def test_clean_runs_with_per_repo_rows_still_pass():
    # Control: per_repo rows on both sides but no errors -> no false positive from the scan.
    baseline = _multi(composite=0.60, per_repo=list(_CLEAN_ROWS), scored_repos=2, repos=2, skipped=0)
    candidate = _multi(per_repo=list(_CLEAN_ROWS), scored_repos=2, repos=2, skipped=0)
    result = check_regression(candidate, baseline)
    assert result["passed"] is True
    assert failed_checks(result) == []
    assert result["composite_delta"] == 0.06


def test_empty_and_missing_per_repo_are_clean():
    # An empty per_repo list and no per_repo key at all both mean "nothing errored", on either side.
    assert check_regression(_multi(per_repo=[]), _multi(composite=0.60, per_repo=[]))["passed"] is True
    assert check_regression(_multi(), _multi(composite=0.60))["passed"] is True


def test_missing_composite_still_fails_both_scored_cleanly():
    # A clean run that simply has no composite (an unscored/errored artifact) still fails
    # both_scored, with the score-missing detail (not an error-side detail).
    result = check_regression({"error": "no tasks"}, _run(0.6))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)
    # this artifact carries a top-level error, so it is reported as a candidate error
    assert _both_detail(result) == "candidate run has a partition or per-repo error"
    # a genuinely score-less but clean artifact reports the missing-score detail
    result2 = check_regression({"scored_repos": 0, "composite_mean": 0.0, "repos": 2}, _run(0.6))
    assert result2["passed"] is False
    assert _both_detail(result2) == "a composite score is missing from one artifact"


def test_non_dict_and_malformed_artifacts_never_raise():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_regression(bad, _run(0.6))
        assert result["passed"] is False
        assert result["checks"]
        assert result["candidate_composite"] is None
        # a non-dict candidate has no error and no score -> missing-score detail, no crash
        assert _both_detail(result) == "a composite score is missing from one artifact"
    # non-dict tuned/held_out inside an otherwise valid artifact
    assert check_regression({"tuned": None, "held_out": None, "composite_mean": 0.66},
                            _multi(composite=0.60))["passed"] is True


def test_malformed_per_repo_shapes_never_raise():
    # Non-dict/non-string rows (ints, None, lists) are ignored; a non-list per_repo container is
    # ignored entirely; blank string rows are not errors. None of these crash the gate.
    assert check_regression(_multi(per_repo=[42, None, [1, 2]]), _multi(composite=0.60))["passed"] is True
    assert check_regression(_multi(per_repo="oops"), _multi(composite=0.60))["passed"] is True
    assert check_regression(_multi(), _multi(composite=0.60, per_repo=["", "   "]))["passed"] is True


def test_a_per_repo_row_that_is_an_error_string_fails_closed():
    # A malformed per-repo entry that is itself a non-empty string is treated as an error record
    # (matches acceptance's no_partition_error, #1056): a corrupt artifact fails closed.
    result = check_regression(_multi(per_repo=[_CLEAN_ROWS[0], "fatal: not a git repository"]),
                              _multi(composite=0.60))
    assert result["passed"] is False
    assert "both_scored" in failed_checks(result)


def test_falsy_per_repo_error_values_are_not_errors():
    # Only a truthy error marks a failed row (the #1056 _partition_error semantics): "", 0, None,
    # and False are not failure records, on either side.
    for falsy in ("", 0, None, False):
        run = _multi(per_repo=[{"repo": "a", "tasks": 4, "error": falsy}])
        assert check_regression(run, _multi(composite=0.60))["passed"] is True, falsy
        assert check_regression(
            _multi(), _multi(composite=0.60, per_repo=[{"repo": "a", "tasks": 4, "error": falsy}]),
        )["passed"] is True, falsy


def test_the_check_list_names_are_unchanged():
    # The fix folds cleanliness into both_scored — no new check name — so downstream consumers of
    # the result shape (e.g. _names assertions) are unaffected.
    result = check_regression(_multi(per_repo=[_BAD_ROW]), _multi(composite=0.60))
    assert _names(result) == ["both_scored", "no_composite_regression", "no_judge_instability_increase"]
