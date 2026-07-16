"""Tests for the challenger-promotion gate (deterministic, offline)."""

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

from benchmark.promotion import (  # noqa: E402
    DEFAULT_MIN_COMPOSITE,
    _check_rows_list,
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


def test_non_finite_composite_does_not_promote():
    # json round-trips Infinity verbatim; an inf composite would trivially clear composite_floor
    # (inf >= min) and promote a malformed run. It must be treated as non-numeric and fail closed,
    # matching score_integrity (#1336) / component_floor.
    for bad in (float("inf"), float("nan"), float("-inf")):
        result = check_promotion(_result(composite=bad, margin=5, disagreement=0.05))
        assert result["passed"] is False, bad
        assert "composite_floor" in failed_checks(result), bad


def test_non_finite_decisive_margin_does_not_beat_baseline():
    result = check_promotion(_result(composite=0.7, margin=float("inf"), disagreement=0.05))
    assert result["passed"] is False
    assert "beats_baseline" in failed_checks(result)


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


def test_decisive_margin_derived_from_judge_report_for_multi_repo():
    # A real run_multi_replay / generalization artifact has NO top-level `tally` or
    # `decisive_margin`; the aggregate win/loss counts live only under `judge_report`.
    # beats_baseline must derive the margin from there instead of holding the run.
    multi = {
        "composite_mean": 0.72,
        "judge_report": {"wins": 9, "losses": 2, "ties": 1, "disagreement_rate": 0.083},
    }
    result = check_promotion(multi, min_composite=0.5, min_decisive_margin=1)
    assert result["decisive_margin"] == 7          # None before the judge_report fallback
    assert "beats_baseline" not in failed_checks(result)
    assert result["passed"] is True


def test_missing_margin_and_tally_fails_beats_baseline():
    result = check_promotion({"composite_mean": 0.7, "judge_report": {"disagreement_rate": 0.1}})
    assert "beats_baseline" in failed_checks(result)
    assert result["decisive_margin"] is None


def test_high_disagreement_is_not_trustworthy():
    result = check_promotion(_result(disagreement=0.8), max_disagreement=0.5)
    assert result["passed"] is False
    assert "judge_trustworthy" in failed_checks(result)


# --- #1249: stale judge_report.disagreement_rate must not false-pass judge_trustworthy -------


def test_stale_judge_report_disagreement_rate_is_recomputed_from_stats():
    art = {
        "composite_mean": 0.7,
        "decisive_margin": 3,
        "judge_report": {"disagreement_rate": 0.05, "dual_order_tasks": 10},
        "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
    }
    result = check_promotion(art, max_disagreement=0.3)
    assert result["passed"] is False
    assert result["disagreement_rate"] == 0.8
    assert "judge_trustworthy" in failed_checks(result)


def test_disagreement_falls_back_to_report_when_stats_absent():
    art = {"composite_mean": 0.7, "decisive_margin": 3,
           "judge_report": {"disagreement_rate": 0.25, "dual_order_tasks": 4}}
    result = check_promotion(art, max_disagreement=0.3)
    assert result["passed"] is True
    assert result["disagreement_rate"] == 0.25


def test_generalization_stale_disagreement_is_recomputed_on_tuned_partition():
    art = _generalization({
        "composite_mean": 0.7,
        "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.05, "dual_order_tasks": 10},
        "judge_order_stats": {"dual_order_tasks": 10, "disagree": 8, "agree": 2, "tie": 0},
    })
    result = check_promotion(art, max_disagreement=0.3)
    assert result["passed"] is False
    assert result["disagreement_rate"] == 0.8
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


# --- #1045: a run_generalization_report is evaluated on its tuned partition ---------------
# A generalization artifact nests every scored field under `tuned`/`held_out` with no top-level
# `composite_mean`/`judge_report`, so reading the top level fails every check vacuously. The gate
# evaluates the tuned partition (the headline figure, mirroring `benchmark.trend.headline_score`).


def _generalization(tuned, held_out=None, gap=0.1):
    return {
        "tuned": tuned,
        "held_out": held_out if held_out is not None else {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": gap,
    }


def test_strong_generalization_run_is_promoted_on_its_tuned_partition():
    art = _generalization({
        "composite_mean": 0.7, "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.1},
    })
    result = check_promotion(art)
    assert result["passed"] is True
    assert result["composite_mean"] == 0.7        # from tuned, not the missing top level
    assert result["decisive_margin"] == 7          # 9 - 2, from tuned's judge_report
    assert result["disagreement_rate"] == 0.1
    assert failed_checks(result) == []


def test_high_tuned_disagreement_fails_judge_trustworthy():
    art = _generalization({
        "composite_mean": 0.7, "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.8},
    })
    result = check_promotion(art, max_disagreement=0.5)
    assert result["passed"] is False
    assert failed_checks(result) == ["judge_trustworthy"]
    assert result["disagreement_rate"] == 0.8      # read from tuned, not None


def test_generalization_below_floor_holds_on_tuned_composite():
    art = _generalization({
        "composite_mean": 0.4, "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.1},
    })
    result = check_promotion(art, min_composite=0.5)
    assert result["passed"] is False
    assert "composite_floor" in failed_checks(result)
    assert result["composite_mean"] == 0.4


def test_unscored_tuned_partition_fails_run_completed():
    # tuned scored no repos: placeholder composite 0.0 is dropped, so the run is not "completed".
    art = _generalization({"composite_mean": 0.0, "scored_repos": 0})
    result = check_promotion(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)
    assert result["composite_mean"] is None


def test_errored_tuned_partition_fails_run_completed():
    art = _generalization({"error": "partition failed", "composite_mean": 0.7, "scored_repos": 3})
    result = check_promotion(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_non_generalization_artifact_still_evaluated_at_top_level():
    # Only both-dict tuned/held_out redirects to a partition; a plain artifact is unaffected.
    plain = _result(composite=0.7, margin=2, disagreement=0.1)
    result = check_promotion(plain)
    assert result["passed"] is True
    assert result["composite_mean"] == 0.7


def test_tuned_partition_without_judge_report_does_not_crash():
    # A tuned partition may carry no judge_report at all; margin/disagreement resolve to None
    # (never a KeyError/AttributeError). beats_baseline holds for lack of a decisive margin, and
    # judge_trustworthy passes as a single-order run with no instability signal.
    art = _generalization({"composite_mean": 0.7, "scored_repos": 3})
    result = check_promotion(art)
    assert result["decisive_margin"] is None
    assert result["disagreement_rate"] is None
    assert failed_checks(result) == ["beats_baseline"]
    trust = next(c for c in result["checks"] if c["name"] == "judge_trustworthy")
    assert trust["passed"] is True


def test_held_out_error_is_ignored_when_tuned_is_strong():
    # The gate reads the tuned partition; a failed held_out partition does not block promotion.
    art = _generalization(
        {"composite_mean": 0.7, "scored_repos": 3,
         "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.1}},
        held_out={"error": "held_out partition failed"},
    )
    result = check_promotion(art)
    assert result["passed"] is True
    assert failed_checks(result) == []


def test_tuned_per_repo_error_fails_run_completed():
    # A repo that failed to clone/freeze in the evaluated (tuned) partition is recorded in
    # per_repo[i], not as a partition-level error. run_completed must still fail — promotion to
    # main must not sign off a run that did not complete clean (mirrors check_acceptance #1056).
    art = _generalization(
        {"composite_mean": 0.8, "scored_repos": 2, "decisive_margin": 5,
         "judge_report": {"disagreement_rate": 0.1},
         "per_repo": [{"repo": "a", "tasks": 5},
                      {"repo": "b", "tasks": 0, "error": "not a git repository"}]},
        held_out={"composite_mean": 0.7, "scored_repos": 2,
                  "per_repo": [{"repo": "c", "tasks": 4}, {"repo": "e", "tasks": 4}]},
    )
    result = check_promotion(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_multi_repo_per_repo_error_fails_run_completed():
    # Same gap for a plain (non-generalization) multi-repo run: a per_repo clone error must fail
    # run_completed even though the aggregate composite is above the floor.
    art = {"composite_mean": 0.8, "decisive_margin": 5, "scored_repos": 2,
           "judge_report": {"disagreement_rate": 0.1},
           "per_repo": [{"repo": "a", "tasks": 5},
                        {"repo": "b", "tasks": 0, "error": "clone failed"}]}
    result = check_promotion(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_partition_level_error_still_detected_alongside_per_repo_error():
    # A partition-level error must NOT be masked when per_repo rows also carry errors: the
    # top-level error is checked first and named, so run_completed fails either way.
    art = _generalization(
        {"composite_mean": 0.8, "scored_repos": 2, "decisive_margin": 5, "error": "partition boom",
         "judge_report": {"disagreement_rate": 0.1},
         "per_repo": [{"repo": "b", "tasks": 0, "error": "clone failed"}]},
    )
    result = check_promotion(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)
    detail = next(c["detail"] for c in result["checks"] if c["name"] == "run_completed")
    assert "partition boom" in detail  # the whole-partition error is surfaced, not swallowed


def test_held_out_per_repo_error_is_ignored_when_tuned_is_clean():
    # Only the evaluated (tuned) partition is scanned; a per_repo error confined to held_out is
    # intentionally ignored, consistent with test_held_out_error_is_ignored_when_tuned_is_strong.
    art = _generalization(
        {"composite_mean": 0.8, "scored_repos": 2, "decisive_margin": 5,
         "judge_report": {"disagreement_rate": 0.1},
         "per_repo": [{"repo": "a", "tasks": 5}, {"repo": "b", "tasks": 5}]},
        held_out={"composite_mean": 0.7, "scored_repos": 1,
                  "per_repo": [{"repo": "c", "tasks": 0, "error": "clone failed"}]},
    )
    result = check_promotion(art)
    assert result["passed"] is True
    assert failed_checks(result) == []


def test_run_completed_tolerates_missing_per_repo_and_non_dict_partition():
    # No AttributeError / KeyError when per_repo is absent, is a non-list, or the partition itself
    # is not a dict: a clean run (no per_repo) still passes; malformed shapes never raise.
    clean = _result(composite=0.7, margin=3, disagreement=0.1)  # no per_repo key at all
    assert check_promotion(clean)["passed"] is True
    non_list = {"composite_mean": 0.7, "decisive_margin": 3,
                "judge_report": {"disagreement_rate": 0.1}, "per_repo": "oops"}
    assert check_promotion(non_list)["passed"] is True  # non-list per_repo ignored, no raise
    # A non-dict tuned is not a generalization pair -> evaluated at top level, no crash.
    non_dict_partition = {"tuned": None, "held_out": {"composite_mean": 0.5},
                          "composite_mean": 0.7, "decisive_margin": 3,
                          "judge_report": {"disagreement_rate": 0.1}}
    assert check_promotion(non_dict_partition)["passed"] is True


def test_partial_partition_without_held_out_is_not_generalization():
    # Only a both-dict tuned/held_out pair is a generalization artifact. A lone tuned block (no
    # held_out) is evaluated at the top level, where there is no composite -> the run is unscored.
    art = {"tuned": {"composite_mean": 0.7, "scored_repos": 3}, "generalization_gap": 0.1}
    result = check_promotion(art)
    assert result["composite_mean"] is None
    assert "run_completed" in failed_checks(result)


def test_non_dict_partition_falls_back_to_top_level():
    # A non-dict tuned (or held_out) is not a partition pair; the top-level fields are used.
    art = {"tuned": None, "held_out": {"composite_mean": 0.5},
           "composite_mean": 0.6, "decisive_margin": 2,
           "judge_report": {"disagreement_rate": 0.1}}
    result = check_promotion(art)
    assert result["passed"] is True
    assert result["composite_mean"] == 0.6


# --- #610: an unscored multi-repo run must not be read as a real 0.0 score --------------
# `run_multi_replay` reports `scored_repos: 0` with a placeholder `composite_mean: 0.0`
# (an average over an empty list). The gate drops that placeholder to None (the same
# `scored_repos` guard `benchmark/report.py` and `scripts/compare_eval.py` already apply), so the
# unscored run fails `run_completed` and can never satisfy `composite_floor` — while a *genuinely*
# scored run whose composite is really 0.0 is preserved.


def test_unscored_multi_repo_placeholder_fails_run_completed():
    # scored_repos: 0 carries composite_mean: 0.0 as a placeholder, not a real score.
    empty_run = {"repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0}
    result = check_promotion(empty_run)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)
    assert result["composite_mean"] is None


def test_unscored_placeholder_is_not_promoted_even_at_permissive_thresholds():
    # Without the guard the placeholder 0.0 would clear a zero floor and a zero-margin bar, so a
    # no-op run that scored nothing could be "promoted". It must stay held: with no real score,
    # BOTH run_completed and composite_floor fail even at min_composite=0.0.
    empty_run = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "tally": {"challenger": 0, "baseline": 0, "tie": 0},
    }
    result = check_promotion(empty_run, min_composite=0.0, min_decisive_margin=0)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)
    assert "composite_floor" in failed_checks(result)


def test_genuine_zero_scored_run_is_a_real_score():
    # Control isolating the cause: same composite_mean 0.0, but scored_repos > 0 means the run
    # really scored 0.0. It must keep its real score (run_completed passes; only the floor fails),
    # proving scored_repos — not the numeric 0.0 — is what marks the placeholder unscored.
    scored_run = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.0,
        "decisive_margin": 2, "judge_report": {"disagreement_rate": 0.1},
    }
    result = check_promotion(scored_run)
    assert "run_completed" not in failed_checks(result)
    assert result["composite_mean"] == 0.0
    assert "composite_floor" in failed_checks(result)  # a real 0.0 is below the default floor


def test_single_repo_zero_composite_is_unaffected():
    # A single-repo run carries no scored_repos key, so its real 0.0 stays a real score — the
    # guard only reinterprets the multi-repo unscored placeholder, not ordinary single-repo runs.
    single = _result(composite=0.0, margin=2, disagreement=0.1)
    result = check_promotion(single)
    assert "run_completed" not in failed_checks(result)
    assert result["composite_mean"] == 0.0


def test_bool_scored_repos_is_not_treated_as_an_unscored_placeholder():
    # scored_repos must be a real int/float count; a bool (isinstance(False, int) is True in
    # Python) is malformed, not the zero placeholder, so the run keeps its real composite and is
    # gated on it rather than silently reinterpreted as unscored.
    run = {
        "repos": 1, "scored_repos": False, "composite_mean": 0.7,
        "decisive_margin": 2, "judge_report": {"disagreement_rate": 0.1},
    }
    result = check_promotion(run)
    assert result["composite_mean"] == 0.7
    assert "run_completed" not in failed_checks(result)


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
    assert "artifact not found" in result.stderr


def test_cli_reports_a_clean_error_for_a_directory_path(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "artifact path is a directory, not a file" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root bypasses file permission bits")
def test_cli_reports_a_clean_error_for_an_unreadable_file(tmp_path):
    locked = tmp_path / "locked.json"
    locked.write_text(json.dumps(_result()), encoding="utf-8")
    locked.chmod(0o000)
    try:
        result = _run_cli(str(locked))
    finally:
        locked.chmod(0o600)
    assert result.returncode == 1
    assert "not readable" in result.stderr
    assert "Traceback" not in result.stderr


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


# --- #741: checks row sanitization for promotion headlines ---------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "run_completed"}, "not a list",
    ({"name": "run_completed", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "run_completed", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "run_completed", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "run_completed", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list([{"name": "run_completed"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_promotion_headline_survives_non_list_checks():
    base = {"passed": False, "composite_mean": 0.5}
    for bad in _MALFORMED_CHECKS:
        assert promotion_headline({**base, "checks": bad}) == (
            "promotion: no checks evaluated"
        ), bad


def test_promotion_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "run_completed"}],
        [{}],
    ):
        assert promotion_headline({"checks": checks, "passed": False}) == (
            "promotion: no checks evaluated"
        )


def test_promotion_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "run_completed", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        line = promotion_headline({"checks": checks, "passed": False})
    assert line == "promotion: HOLD (1/1 checks failed: run_completed)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_promotion_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        line = promotion_headline({"checks": 42, "passed": False})
    assert line == "promotion: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "run_completed"}],
        [{}],
        [42],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "run_completed", "passed": False},
        42,
        {"name": "composite_floor", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.promotion"):
        assert failed_checks({"checks": checks}) == ["run_completed"]
    assert any("checks[1] is int" in r.message for r in caplog.records)
