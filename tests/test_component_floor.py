"""Tests for the per-component score-floor gate (deterministic, offline)."""

import copy
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_floor import (  # noqa: E402
    DEFAULT_MIN_COMPOSITE,
    _artifact_error,
    _check_rows_list,
    _floor_source,
    check_component_floors,
    component_floor_headline,
    failed_checks,
)


def _result(composite, judge, objective):
    return {"composite_mean": composite,
            "composite_parts": {"judge_mean": judge, "objective_mean": objective}}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_all_components_above_floors_passes():
    result = check_component_floors(_result(0.62, 0.7, 0.55))
    assert result["passed"] is True
    assert _names(result) == ["run_completed", "composite_floor", "judge_floor", "objective_floor"]
    assert result["composite_mean"] == 0.62 and result["judge_mean"] == 0.7


def test_a_weak_objective_anchor_is_caught_even_with_a_good_composite():
    # The differentiator: composite and judge clear their floors, but the objective anchor is
    # weak (fluff won the judge). --fail-under on the composite alone would miss this.
    result = check_component_floors(_result(0.55, 0.9, 0.2),
                                    min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is False
    assert failed_checks(result) == ["objective_floor"]


def test_a_weak_judge_is_caught():
    result = check_component_floors(_result(0.55, 0.2, 0.9), min_judge=0.4)
    assert result["passed"] is False
    assert "judge_floor" in failed_checks(result)


def test_composite_below_floor_is_caught():
    result = check_component_floors(_result(0.30, 0.7, 0.6), min_composite=0.5)
    assert result["passed"] is False
    assert "composite_floor" in failed_checks(result)


def test_non_finite_composite_fails_the_floor_not_passes_it():
    # json round-trips Infinity verbatim; an inf composite_mean would trivially clear every floor
    # (inf >= min is True), false-passing a malformed run. It must fail the floor closed instead,
    # matching score_integrity (#1336).
    result = check_component_floors(_result(float("inf"), 0.7, 0.6))
    assert result["passed"] is False
    assert "composite_floor" in failed_checks(result)


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf")])
def test_non_finite_component_mean_fails_its_floor(bad):
    result = check_component_floors(_result(0.6, bad, 0.6))
    assert result["passed"] is False
    assert "judge_floor" in failed_checks(result)


def test_floors_are_inclusive():
    assert check_component_floors(_result(0.5, 0.4, 0.4),
                                  min_composite=0.5, min_judge=0.4, min_objective=0.4)["passed"] is True
    assert check_component_floors(_result(0.49, 0.4, 0.4), min_composite=0.5)["passed"] is False


def test_all_floors_are_configurable():
    run = _result(0.6, 0.5, 0.5)
    assert check_component_floors(run, min_composite=0.5, min_judge=0.4, min_objective=0.4)["passed"] is True
    assert check_component_floors(run, min_composite=0.7)["passed"] is False
    assert check_component_floors(run, min_judge=0.6)["passed"] is False
    assert check_component_floors(run, min_objective=0.6)["passed"] is False


def test_missing_components_fail_their_floors():
    result = check_component_floors({"composite_mean": 0.6, "composite_parts": {}})
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"judge_floor", "objective_floor"}
    assert result["judge_mean"] is None and result["objective_mean"] is None


def _partial_multi(composite=0.66, judge=0.7, objective=0.62):
    return {
        "composite_mean": composite,
        "scored_repos": 2,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
        "per_repo": [
            {"repo": "a", "tasks": 4},
            {"repo": "b", "tasks": 3},
            {"repo": "c", "tasks": 0, "error": "clone failed"},
        ],
    }


def test_multi_repo_per_repo_error_fails_run_completed():
    result = check_component_floors(_partial_multi())
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)
    detail = next(c["detail"] for c in result["checks"] if c["name"] == "run_completed")
    assert "clone failed" in detail


def test_tuned_per_repo_error_fails_run_completed():
    art = {
        "tuned": {
            "composite_mean": 0.66,
            "scored_repos": 2,
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.62},
            "per_repo": [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 0, "error": "freeze failed"}],
        },
        "held_out": {"composite_mean": 0.55, "scored_repos": 2, "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.5}},
        "generalization_gap": 0.11,
    }
    result = check_component_floors(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_held_out_per_repo_error_is_ignored_when_tuned_is_clean():
    art = {
        "tuned": {
            "composite_mean": 0.66,
            "scored_repos": 2,
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.62},
            "per_repo": [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 3}],
        },
        "held_out": {
            "composite_mean": 0.55,
            "scored_repos": 1,
            "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.5},
            "per_repo": [{"repo": "x", "tasks": 0, "error": "clone failed"}],
        },
        "generalization_gap": 0.11,
    }
    assert check_component_floors(art)["passed"] is True


def test_run_completed_tolerates_missing_per_repo_and_non_list_per_repo():
    clean = _result(0.66, 0.7, 0.62)
    assert check_component_floors(clean)["passed"] is True
    weird = {**clean, "per_repo": "oops"}
    assert check_component_floors(weird)["passed"] is True


def test_run_completed_per_repo_none_does_not_crash():
    art = {**_result(0.66, 0.7, 0.62), "per_repo": None}
    assert check_component_floors(art)["passed"] is True


def test_run_completed_per_repo_with_none_and_non_dict_entries_does_not_crash():
    art = {**_result(0.66, 0.7, 0.62), "per_repo": [{"repo": "a", "tasks": 4}, None, 42]}
    assert check_component_floors(art)["passed"] is True


def test_falsy_per_repo_error_values_do_not_fail_run_completed():
    for falsy in (0, False, None, ""):
        art = _partial_multi()
        art["per_repo"][-1]["error"] = falsy
        assert check_component_floors(art)["passed"] is True, falsy


def test_bare_string_per_repo_row_fails_run_completed():
    art = _result(0.66, 0.7, 0.62)
    art["per_repo"] = [{"repo": "a", "tasks": 4}, "corrupt row"]
    result = check_component_floors(art)
    assert result["passed"] is False
    assert "run_completed" in failed_checks(result)


def test_lone_tuned_without_held_out_is_not_treated_as_generalization():
    art = {
        "composite_mean": 0.66,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.62},
        "tuned": {"per_repo": [{"repo": "b", "tasks": 0, "error": "clone failed"}]},
    }
    assert check_component_floors(art)["passed"] is True


def test_zero_composite_passes_run_completed():
    # A genuine 0.0 score must not be treated as absent — bool(0.0) is False but 0.0 is valid.
    result = check_component_floors(_result(0.0, 0.0, 0.0), min_composite=0.0, min_judge=0.0, min_objective=0.0)
    assert result["passed"] is True
    assert next(c for c in result["checks"] if c["name"] == "run_completed")["passed"] is True


def test_falsy_top_level_error_values_do_not_fail_run_completed():
    for falsy in (0, False, None, ""):
        art = _result(0.66, 0.7, 0.62)
        art["error"] = falsy
        result = check_component_floors(art)
        assert result["passed"] is True, falsy
        assert next(c for c in result["checks"] if c["name"] == "run_completed")["passed"] is True


def test_artifact_error_helper_reports_top_level_and_per_repo_errors():
    assert _artifact_error({"error": "boom"}) == "boom"
    assert _artifact_error(_partial_multi()) == "clone failed"
    assert _artifact_error(_result(0.66, 0.7, 0.62)) is None
    assert _artifact_error("not a dict") is None


def test_floor_source_helper_requires_both_generalization_partitions():
    art = {"composite_mean": 0.66, "tuned": {"composite_mean": 0.1}}
    assert _floor_source(art) is art
    gen = {
        "tuned": {"composite_mean": 0.66},
        "held_out": {"composite_mean": 0.55},
        "generalization_gap": 0.11,
    }
    assert _floor_source(gen) is gen["tuned"]


def test_artifact_error_helper_survives_non_dict_partition(monkeypatch):
    import benchmark.component_floor as cf

    def _boom(partition):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(cf, "_partition_error", _boom)
    assert _artifact_error({"composite_mean": 0.66, "scored_repos": 1}) == "partition error scan failed"


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_component_floors(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["composite_mean"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"composite_mean": "high", "composite_parts": {"judge_mean": "a", "objective_mean": None}}
    result = check_component_floors(weird)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"run_completed", "composite_floor", "judge_floor", "objective_floor"}


def test_headline_reports_pass_and_fail():
    assert "PASS" in component_floor_headline(check_component_floors(_result(0.62, 0.7, 0.6)))
    fail = component_floor_headline(check_component_floors(_result(0.55, 0.9, 0.1)))
    assert "FAIL" in fail and "objective_floor" in fail


# --- #1126: failed_checks / headline must sanitize a malformed `checks` container / rows -------
# check_component_floors always emits well-formed rows, but a hand-built or deserialized result
# can carry a truthy non-list `checks` or non-dict / key-missing rows. The helpers route through
# _check_rows_list (the same contract as promotion / judge_gate / coverage) instead of crashing.


@pytest.mark.parametrize("bad", ["garbage", 42, 3.14, {"name": "x"}, (1, 2), True])
def test_failed_checks_survives_non_list_checks(bad):
    # a truthy non-list `checks` would crash `c.get(...)` / iteration without the guard.
    assert failed_checks({"checks": bad}) == []
    assert component_floor_headline({"checks": bad}) == "component floors: no checks evaluated"


def test_failed_checks_skips_non_dict_and_key_missing_rows():
    mixed = {"checks": [
        {"name": "composite_floor", "passed": False},  # kept — a real failure
        "junk",                                          # non-dict, skipped
        {"passed": True},                                # missing name, skipped
        {"name": "obj"},                                 # missing passed, skipped
        {"name": "judge_floor", "passed": True},         # kept, but passed -> not failed
    ]}
    assert failed_checks(mixed) == ["composite_floor"]


def test_check_rows_list_filters_and_counts():
    rows = [{"name": "a", "passed": True}, {"name": "b", "passed": False}]
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []
    assert _check_rows_list("nope") == []
    # only unusable rows -> empty (drives the "no checks evaluated" headline)
    assert _check_rows_list(["x", {"passed": True}]) == []


def test_headline_reports_count_over_total_usable_rows():
    # 1 failed of 2 usable rows; a junk row is excluded from the denominator, not counted.
    result = {"passed": False, "checks": [
        {"name": "judge_floor", "passed": False},
        {"name": "obj", "passed": True},
        "junk",
    ]}
    assert component_floor_headline(result) == (
        "component floors: FAIL (1/2 below floor: judge_floor)"
    )


def test_check_rows_list_warns_on_non_list(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.component_floor"):
        assert _check_rows_list("garbage") == []
    assert any("checks is str" in r.message for r in caplog.records)
    assert component_floor_headline({}) == "component floors: no checks evaluated"
    assert DEFAULT_MIN_COMPOSITE == 0.5


def test_every_floor_reported_even_when_all_fail():
    result = check_component_floors(_result(0.1, 0.1, 0.1))
    assert len(result["checks"]) == 4
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_stricter_than_a_single_composite_floor():
    # Two runs with the SAME composite (0.55, above a 0.5 --fail-under floor): the balanced one
    # passes, the fluff-driven one (weak objective anchor) is blocked. This is the whole point:
    # a per-component gate catches what a single composite floor cannot.
    balanced = check_component_floors(_result(0.55, 0.55, 0.55), min_composite=0.5,
                                      min_judge=0.4, min_objective=0.4)
    fluff = check_component_floors(_result(0.55, 0.95, 0.15), min_composite=0.5,
                                   min_judge=0.4, min_objective=0.4)
    assert balanced["passed"] is True
    assert fluff["passed"] is False and failed_checks(fluff) == ["objective_floor"]


def test_gates_a_multi_repo_result_with_top_level_parts():
    # A multi-repo aggregate carries composite_parts at the top level, so it gates the same way.
    multi = {"repos": 3, "scored_repos": 3, "composite_mean": 0.6,
             "composite_parts": {"judge_mean": 0.62, "objective_mean": 0.58}, "per_repo": []}
    result = check_component_floors(multi, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is True
    assert result["judge_mean"] == 0.62 and result["objective_mean"] == 0.58


def test_a_perfect_judge_cannot_rescue_a_zero_anchor():
    # The extreme: judge 1.0 but the objective anchor is 0.0 -> blocked on the anchor floor.
    result = check_component_floors(_result(0.6, 1.0, 0.0), min_objective=0.4)
    assert result["passed"] is False
    assert "objective_floor" in failed_checks(result)
    assert "FAIL" in component_floor_headline(result)


def test_check_component_floors_does_not_mutate_the_result():
    run = _result(0.62, 0.7, 0.6)
    snapshot = copy.deepcopy(run)
    check_component_floors(run)
    assert run == snapshot


# --- unscored multi-repo placeholder must not be read as a real 0.0 score ---------------
# `run_multi_replay` reports `scored_repos: 0` with placeholder means of `0.0` (averages over
# empty lists). The gate drops those placeholders to None (same `scored_repos` guard promotion and
# `run_eval --fail-under` already apply), so an unscored run never clears the floors — while a
# genuinely scored run whose components are really 0.0 is preserved.


def test_unscored_multi_repo_placeholder_fails_all_floors():
    empty_run = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(empty_run)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"run_completed", "composite_floor", "judge_floor", "objective_floor"}
    assert result["composite_mean"] is None
    assert result["judge_mean"] is None
    assert result["objective_mean"] is None


def test_unscored_placeholder_is_not_passed_even_at_permissive_floors():
    # Without the guard the placeholder 0.0 would clear zero floors and a no-op run that scored
    # nothing could pass. It must stay held even at min_* = 0.0.
    empty_run = {
        "repos": 2, "scored_repos": 0, "skipped": 2, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(empty_run, min_composite=0.0, min_judge=0.0, min_objective=0.0)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"run_completed", "composite_floor", "judge_floor", "objective_floor"}


def test_genuine_zero_scored_run_is_a_real_score():
    # Control: same 0.0 means, but scored_repos > 0 means the run really scored 0.0. It must keep
    # its real values and be gated on them — proving scored_repos, not the numeric 0.0, marks the
    # placeholder unscored.
    scored_run = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    result = check_component_floors(scored_run)
    assert result["composite_mean"] == 0.0
    assert result["judge_mean"] == 0.0
    assert result["objective_mean"] == 0.0
    assert set(failed_checks(result)) == {"composite_floor", "judge_floor", "objective_floor"}


def test_single_repo_zero_components_are_unaffected():
    # A single-repo run carries no scored_repos key, so its real 0.0 stays a real score.
    result = check_component_floors(_result(0.0, 0.0, 0.0))
    assert result["composite_mean"] == 0.0
    assert result["judge_mean"] == 0.0
    assert result["objective_mean"] == 0.0


def test_bool_scored_repos_is_not_treated_as_an_unscored_placeholder():
    # scored_repos must be a real int/float count; a bool is malformed, not the zero placeholder.
    run = {
        "repos": 1, "scored_repos": False, "composite_mean": 0.7,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.5},
    }
    result = check_component_floors(run)
    assert result["composite_mean"] == 0.7
    assert result["judge_mean"] == 0.6
    assert result["passed"] is True


# --- generalization: evaluate the tuned partition (mirrors check_promotion / check_judge) ----

def _generalization(tuned, held_out=None, gap=0.1):
    return {
        "tuned": tuned,
        "held_out": held_out or {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": gap,
    }


def test_strong_generalization_run_passes_on_its_tuned_partition():
    art = _generalization({
        "scored_repos": 3,
        "composite_mean": 0.65,
        "composite_parts": {"judge_mean": 0.70, "objective_mean": 0.55},
    })
    result = check_component_floors(art, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is True
    assert result["composite_mean"] == 0.65
    assert result["judge_mean"] == 0.70
    assert result["objective_mean"] == 0.55


def test_generalization_weak_objective_on_tuned_is_caught():
    art = _generalization({
        "scored_repos": 3,
        "composite_mean": 0.55,
        "composite_parts": {"judge_mean": 0.9, "objective_mean": 0.2},
    })
    result = check_component_floors(art, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is False
    assert failed_checks(result) == ["objective_floor"]


def test_unscored_tuned_partition_fails_all_floors():
    art = _generalization({
        "scored_repos": 0,
        "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    })
    result = check_component_floors(art)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {"run_completed", "composite_floor", "judge_floor", "objective_floor"}
    assert result["composite_mean"] is None


def test_partial_partition_without_held_out_is_not_generalization():
    art = {
        "tuned": {
            "scored_repos": 3,
            "composite_mean": 0.65,
            "composite_parts": {"judge_mean": 0.70, "objective_mean": 0.55},
        },
        "generalization_gap": 0.1,
    }
    result = check_component_floors(art, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is False
    assert result["composite_mean"] is None


def test_held_out_weak_components_do_not_affect_tuned_gate():
    art = _generalization(
        {"scored_repos": 3, "composite_mean": 0.65,
         "composite_parts": {"judge_mean": 0.70, "objective_mean": 0.55}},
        {"scored_repos": 3, "composite_mean": 0.1,
         "composite_parts": {"judge_mean": 0.1, "objective_mean": 0.1}},
    )
    result = check_component_floors(art, min_composite=0.5, min_judge=0.4, min_objective=0.4)
    assert result["passed"] is True


# --- CLI: a bad artifact must never surface a raw traceback (#1267) -------------------


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.component_floor", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _run_main_in_process(monkeypatch, argv):
    import scripts.component_floor as component_floor_cli

    monkeypatch.setattr(sys, "argv", ["scripts.component_floor", *argv])
    with pytest.raises(SystemExit) as excinfo:
        component_floor_cli.main()
    return excinfo.value.code


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the FileNotFoundError message itself, naming the offending path
    assert "No such file or directory" in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(invalid))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the JSONDecodeError message with its parse position, not just "no traceback"
    assert "Expecting property name enclosed in double quotes" in result.stderr
    assert "line 1" in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    bad = _write(tmp_path / "bad.json", [1, 2, 3])
    result = _run_cli(bad)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # load_artifact's ValueError message, naming the offending path
    assert "must be a JSON object" in result.stderr
    assert bad in result.stderr


def test_cli_reports_a_clean_error_for_a_directory_path(tmp_path):
    # IsADirectoryError is an OSError; end-to-end proof the guard covers the family even
    # when the suite runs as root (a chmod-000 fixture would be readable to root).
    unreadable = tmp_path / "a-directory"
    unreadable.mkdir()
    result = _run_cli(str(unreadable))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(unreadable) in result.stderr


def test_cli_reports_a_clean_error_for_a_permission_denied_file(tmp_path, monkeypatch, capsys):
    # In-process, so it holds under any uid (root reads chmod-000 files, so a filesystem
    # fixture cannot force EACCES deterministically): PermissionError must surface as the
    # one-line OSError message and a clean exit 1, never a traceback.
    import scripts.component_floor as component_floor_cli

    denied = str(tmp_path / "denied.json")

    def _deny(path):
        raise PermissionError(13, "Permission denied", denied)

    monkeypatch.setattr(component_floor_cli, "load_artifact", _deny)
    code = _run_main_in_process(monkeypatch, [denied])
    assert code == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err
    assert denied in err


def test_cli_reports_a_clean_error_when_the_floor_check_itself_fails(tmp_path, monkeypatch, capsys):
    # The guard is not just around loading: if the floor evaluation blows up on artifact
    # content, the CLI must still exit 1 with a one-line error instead of a traceback.
    import scripts.component_floor as component_floor_cli

    good = _write(tmp_path / "good.json", _result(0.62, 0.7, 0.55))

    def _boom(artifact, min_composite, min_judge, min_objective):
        raise TypeError("unhashable artifact content")

    monkeypatch.setattr(component_floor_cli, "check_component_floors", _boom)
    code = _run_main_in_process(monkeypatch, [good])
    assert code == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "cannot evaluate artifact" in err


def test_cli_runs_the_gate_and_emits_the_result_for_a_well_formed_artifact(tmp_path):
    # Success path: exit 0, and the gate logic actually ran -- stdout carries the full result
    # (every floor check) and stderr carries the headline plus a PASS line per check.
    good = _write(tmp_path / "good.json", _result(0.62, 0.7, 0.55))
    result = _run_cli(good)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr

    payload = json.loads(result.stdout)
    assert payload["passed"] is True
    assert [c["name"] for c in payload["checks"]] == [
        "run_completed", "composite_floor", "judge_floor", "objective_floor",
    ]
    assert payload["composite_mean"] == 0.62 and payload["judge_mean"] == 0.7
    assert "[PASS] composite_floor" in result.stderr


def test_cli_strict_exits_nonzero_when_a_floor_is_missed(tmp_path):
    # --strict turns a missed floor into a CI failure, and still prints the result cleanly.
    weak = _write(tmp_path / "weak.json", _result(0.55, 0.9, 0.2))
    result = _run_cli(weak, "--strict")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["passed"] is False
    assert "[FAIL] objective_floor" in result.stderr


def test_cli_without_strict_exits_zero_even_when_a_floor_is_missed(tmp_path):
    weak = _write(tmp_path / "weak.json", _result(0.55, 0.9, 0.2))
    result = _run_cli(weak)
    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is False
