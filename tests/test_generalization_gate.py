"""Tests for the generalization gate (deterministic, offline)."""

import copy
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.generalization_gate import (  # noqa: E402
    DEFAULT_MAX_GAP,
    DEFAULT_MIN_HELD_OUT_REPOS,
    _check_rows_list,
    _composite,
    check_generalization,
    failed_checks,
    generalization_headline,
)
from scripts import generalization_gate as cli  # noqa: E402


def _gen(tuned, held, held_repos=3):
    return {
        "tuned": {"composite_mean": tuned, "scored_repos": 4},
        "held_out": {"composite_mean": held, "scored_repos": held_repos},
        "generalization_gap": round(tuned - held, 3),
    }


def _part(scored, composite):
    return {"composite_mean": composite, "scored_repos": scored}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_run_that_generalizes_passes():
    result = check_generalization(_gen(0.68, 0.63), max_gap=0.1)   # gap 0.05
    assert result["passed"] is True
    assert _names(result) == ["has_partitions", "no_partition_error", "enough_held_out_repos", "gap_within_tolerance"]
    assert result["gap"] == 0.05 and result["held_out_repos"] == 3


def test_a_large_gap_fails_gap_within_tolerance():
    result = check_generalization(_gen(0.70, 0.40), max_gap=0.1)   # gap 0.30
    assert result["passed"] is False
    assert failed_checks(result) == ["gap_within_tolerance"]
    assert result["gap"] == 0.30


def test_the_gap_bound_is_inclusive():
    assert check_generalization(_gen(0.70, 0.60), max_gap=0.1)["passed"] is True   # gap exactly 0.1
    assert check_generalization(_gen(0.71, 0.60), max_gap=0.1)["passed"] is False  # gap 0.11


# --- a partition that scored no repos reports a placeholder composite, not a real score ---------
# scored_repos: 0 carries composite_mean 0.0 (an average over an empty list). Reading it as a real
# score let the gate sign off "GENERALIZES" on a run whose tuned partition never scored — the
# placeholder 0.0 makes the tuned-minus-held-out gap negative ("held-out beat tuned"), which is
# always within tolerance. The composite is guarded as headline_score/promotion/component_floor do.


def test_an_unscored_tuned_partition_is_not_generalization():
    # tuned scored nothing (placeholder 0.0), held-out scored fine. Pre-fix the gate PASSED
    # ("GENERALIZES", gap -0.55); it must fail closed instead.
    result = check_generalization({"tuned": _part(0, 0.0), "held_out": _part(3, 0.55),
                                   "generalization_gap": None})
    assert result["passed"] is False
    assert result["tuned_composite"] is None and result["gap"] is None
    assert set(failed_checks(result)) >= {"has_partitions", "gap_within_tolerance"}
    assert "GENERALIZES" not in generalization_headline(result)


def test_an_unscored_held_out_partition_is_not_generalization():
    result = check_generalization({"tuned": _part(4, 0.65), "held_out": _part(0, 0.0),
                                   "generalization_gap": None})
    assert result["passed"] is False and "has_partitions" in failed_checks(result)


def test_a_genuinely_scored_zero_composite_is_kept():
    # Control isolating the cause: scored_repos > 0 with a real 0.0 composite keeps its score and is
    # evaluated on the gap (here tuned 0.0 vs held-out 0.0 = gap 0.0, within tolerance) — proving
    # scored_repos, not the numeric 0.0, is what marks a partition unscored.
    result = check_generalization({"tuned": _part(4, 0.0), "held_out": _part(3, 0.0),
                                   "generalization_gap": 0.0})
    assert result["tuned_composite"] == 0.0 and result["gap"] == 0.0 and result["passed"] is True


def test_composite_helper_guards_unscored_and_tolerates_malformed():
    assert _composite(_part(0, 0.0)) is None          # scored_repos 0 -> placeholder -> None
    assert _composite(_part(0.0, 0.0)) is None         # float 0.0 count is still the placeholder
    assert _composite(_part(4, 0.0)) == 0.0            # scored -> real 0.0 kept
    assert _composite({"composite_mean": 0.6}) == 0.6  # no scored_repos key -> single-repo score
    assert _composite({"scored_repos": False, "composite_mean": 0.6}) == 0.6  # bool is not a count
    # A non-dict partition yields None (no crash); a non-numeric scored_repos is not the 0
    # placeholder, so the real composite is kept.
    for bad in (None, "x", 42, [1]):
        assert _composite(bad) is None
    assert _composite({"scored_repos": "n", "composite_mean": 0.6}) == 0.6
    assert _composite({"scored_repos": 2, "composite_mean": "bad"}) is None    # non-numeric score


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_composite_is_not_a_real_score(bad):
    # json round-trips NaN/Infinity verbatim, so a non-finite composite_mean reaches the gate. It
    # is not a real score: _composite must degrade it to None exactly as it does an unscored
    # partition, guarded as headline_score/promotion/component_floor do. Otherwise an Infinity
    # held-out composite makes gap -inf, false-passes gap_within_tolerance, and signs off
    # "GENERALIZES" with inf/nan surfacing in the headline instead of degrading to n/a.
    assert _composite(_part(4, bad)) is None
    result = check_generalization({"tuned": _part(4, 0.70), "held_out": _part(3, bad),
                                   "generalization_gap": None})
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["held_out_composite"] is None and result["gap"] is None
    headline = generalization_headline(result)
    assert "GENERALIZES" not in headline
    assert "inf" not in headline.lower() and "nan" not in headline.lower()


def test_an_oversized_int_scored_repos_does_not_crash_and_fails_closed():
    # math.isfinite raises OverflowError on a Python int too large to convert to a float, and
    # json parses an arbitrarily long integer literal into an int -- so an oversized scored_repos
    # must be guarded, not crash the gate. It is treated as non-numeric: enough_held_out_repos
    # fails closed and held_out_repos is unavailable (mirrors gap_outlook #1479 / skip_share #1502).
    big = 10 ** 400
    result = check_generalization(
        {"tuned": _part(4, 0.68), "held_out": {"composite_mean": 0.66, "scored_repos": big}},
        max_gap=0.1, min_held_out_repos=2,
    )
    assert result["passed"] is False
    assert "enough_held_out_repos" in failed_checks(result)
    assert result["held_out_repos"] is None


def test_an_oversized_int_composite_is_not_a_real_score():
    big = 10 ** 400
    assert _composite({"scored_repos": 4, "composite_mean": big}) is None
    result = check_generalization(
        {"tuned": {"composite_mean": big, "scored_repos": 4}, "held_out": _part(3, 0.66)},
        max_gap=0.1,
    )
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["tuned_composite"] is None and result["gap"] is None


def test_a_held_out_score_above_tuned_is_within_tolerance():
    # Negative gap (held-out beat tuned) always passes the tolerance check.
    result = check_generalization(_gen(0.60, 0.66), max_gap=0.1)
    assert result["gap"] == -0.06
    assert result["passed"] is True


def test_too_few_held_out_repos_fails():
    result = check_generalization(_gen(0.68, 0.63, held_repos=2), min_held_out_repos=3)
    assert result["passed"] is False
    assert "enough_held_out_repos" in failed_checks(result)
    assert result["held_out_repos"] == 2


def test_held_out_repo_count_falls_back_to_per_repo_length():
    result = check_generalization({
        "tuned": {"composite_mean": 0.68},
        "held_out": {"composite_mean": 0.63, "per_repo": [{"repo": "a"}, {"repo": "b"}, {"repo": "c"}]},
    }, min_held_out_repos=3)
    assert result["held_out_repos"] == 3
    assert result["passed"] is True


def test_thresholds_are_configurable():
    run = _gen(0.70, 0.62, held_repos=3)                  # gap 0.08
    assert check_generalization(run, max_gap=0.1, min_held_out_repos=3)["passed"] is True
    assert check_generalization(run, max_gap=0.05)["passed"] is False
    assert check_generalization(run, min_held_out_repos=4)["passed"] is False


def test_a_missing_partition_fails_has_partitions():
    result = check_generalization({"tuned": {"composite_mean": 0.68}}, max_gap=0.1)
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["gap"] is None


def test_a_single_repo_artifact_fails_gracefully():
    result = check_generalization({"composite_mean": 0.6, "tasks": 8})
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)
    assert result["tuned_composite"] is None and result["held_out_composite"] is None


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_generalization(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["gap"] is None


def test_non_numeric_composites_do_not_crash():
    weird = {"tuned": {"composite_mean": "high"}, "held_out": {"composite_mean": None}}
    result = check_generalization(weird)
    assert result["passed"] is False
    assert "has_partitions" in failed_checks(result)


def test_the_gap_is_recomputed_not_taken_from_a_stale_field():
    # A stale/incorrect generalization_gap field is ignored; the gap comes from the composites.
    run = _gen(0.70, 0.60)
    run["generalization_gap"] = -99.0
    assert check_generalization(run)["gap"] == 0.10


def test_a_float_precision_gap_is_rounded_to_the_bound():
    # 0.70 - 0.60 rounds to exactly 0.10, not 0.10000000000000009, so the inclusive bound holds.
    assert check_generalization(_gen(0.70, 0.60), max_gap=0.1)["gap"] == 0.1


def test_headline_reports_generalizes_and_overfit():
    assert "GENERALIZES" in generalization_headline(check_generalization(_gen(0.68, 0.63)))
    overfit = generalization_headline(check_generalization(_gen(0.70, 0.40)))
    assert "OVERFIT" in overfit
    # No bare "None" even when a partition is missing.
    missing = generalization_headline(check_generalization({"tuned": {"composite_mean": 0.6}}))
    assert "None" not in missing
    assert DEFAULT_MAX_GAP == 0.1 and DEFAULT_MIN_HELD_OUT_REPOS == 3


def test_headline_handles_a_result_with_no_checks():
    assert generalization_headline({}) == "generalization: no checks evaluated"
    assert generalization_headline("not a dict") == "generalization: no checks evaluated"
    assert generalization_headline({"checks": []}) == "generalization: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_generalization(_gen(0.70, 0.40))) != []


# --- a non-list / malformed `checks` field must not crash the reporting helpers ----------------
# check_generalization always emits a list of well-formed rows, but a hand-built or deserialized
# result whose `checks` isn't a list used to crash failed_checks / the headline on `c["name"]`.

_MALFORMED_CHECKS = ["not a list", 42, 3.14, True, {"name": "has_partitions"}, ("a", "b"), range(2)]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "has_partitions", "passed": True}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad


def test_check_rows_list_skips_unusable_rows():
    checks = [
        {"name": "keep", "passed": False},
        "not a dict",
        {"passed": True},                       # missing name
        {"name": "no_passed"},                   # missing passed
        {"name": 42, "passed": True},            # non-str name
        {"name": "bad_passed", "passed": "yes"},  # non-bool passed
    ]
    assert _check_rows_list(checks) == [{"name": "keep", "passed": False}]


def test_check_rows_list_warns_when_every_row_is_unusable(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.generalization_gate"):
        assert _check_rows_list([42, "bad", None]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_failed_checks_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_headline_survives_a_non_list_checks_field():
    for bad in _MALFORMED_CHECKS:
        assert generalization_headline({"checks": bad}) == "generalization: no checks evaluated", bad


def test_helpers_log_a_warning_for_a_non_list_checks_field(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.generalization_gate"):
        assert failed_checks({"checks": "garbage"}) == []
    assert any("checks is str" in r.message for r in caplog.records)


def test_check_generalization_does_not_mutate_the_result():
    run = _gen(0.68, 0.63)
    snapshot = copy.deepcopy(run)
    check_generalization(run)
    assert run == snapshot


# --- no_partition_error: a partition that did not complete clean must fail the gate (#1329) ---
# check_generalization uses BOTH partitions for its decision, so a top-level error or a per_repo
# clone/freeze failure in EITHER tuned or held_out must fail no_partition_error -- mirroring
# check_acceptance and check_promotion.run_completed -- or a partial, biased run signs off as
# GENERALIZES.


def _gen_pr(tuned_per_repo, held_per_repo):
    result = _gen(0.68, 0.63)   # gap 0.05, would otherwise pass
    result["tuned"]["per_repo"] = tuned_per_repo
    result["held_out"]["per_repo"] = held_per_repo
    return result


def test_a_held_out_per_repo_error_fails_no_partition_error():
    result = check_generalization(
        _gen_pr(
            [{"repo": "a", "tasks": 4}],
            [{"repo": "b", "tasks": 4}, {"repo": "c", "tasks": 0, "error": "failed to clone"}],
        )
    )
    assert result["passed"] is False
    assert "no_partition_error" in failed_checks(result)


def test_a_tuned_per_repo_error_fails_no_partition_error():
    result = check_generalization(
        _gen_pr(
            [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 0, "error": "not a git repo"}],
            [{"repo": "c", "tasks": 4}],
        )
    )
    assert result["passed"] is False
    assert "no_partition_error" in failed_checks(result)


def test_a_top_level_partition_error_fails_no_partition_error():
    result = _gen(0.68, 0.63)
    result["held_out"]["error"] = "RepoSetError: no repos to replay"
    out = check_generalization(result)
    assert out["passed"] is False
    assert "no_partition_error" in failed_checks(out)


def test_clean_per_repo_rows_still_pass_no_partition_error():
    # Control: per_repo rows present but none carry an error -> the gate still passes.
    result = check_generalization(
        _gen_pr([{"repo": "a", "tasks": 4}], [{"repo": "b", "tasks": 4}, {"repo": "c", "tasks": 5}])
    )
    assert "no_partition_error" not in failed_checks(result)
    assert result["passed"] is True


def test_cli_directory_path_exits_two(tmp_path):
    # Invoking the gate CLI on a directory artifact path is an OSError (IsADirectoryError on
    # POSIX, PermissionError on Windows), not a FileNotFoundError -- it must exit 2 with an
    # actionable message rather than dumping a raw traceback.
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.generalization_gate", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 2
    assert "directory" in proc.stderr or "not readable" in proc.stderr
    assert "Traceback" not in proc.stderr


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    # Platform-agnostic: a real directory never raises IsADirectoryError on Windows (it raises
    # PermissionError), so force it to prove the dedicated handler is not dead code. On every
    # platform load_artifact must raise SystemExit(2) with the specific directory message and no
    # traceback.
    def _raise_is_a_directory(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise_is_a_directory)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err
    assert "Traceback" not in err
