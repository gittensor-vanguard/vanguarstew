"""Tests for the sample-adequacy gate (deterministic, offline)."""

import copy
import logging
import os
import stat
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.sample_adequacy import (  # noqa: E402
    DEFAULT_MIN_TASKS,
    _check_rows_list,
    check_sample_adequacy,
    failed_checks,
    sample_adequacy_headline,
)
from scripts import sample_adequacy as cli  # noqa: E402


def _run(tasks, challenger=None, baseline=None, tie=None):
    result = {"tasks": tasks, "composite_mean": 0.6}
    if challenger is not None:
        result["tally"] = {"challenger": challenger, "baseline": baseline, "tie": tie}
    return result


def _multi(*per_repo_tasks):
    return {"per_repo": [{"repo": f"r{i}", "tasks": t} for i, t in enumerate(per_repo_tasks)]}


def _gen(tuned_tasks, held_tasks):
    return {
        "tuned": {"per_repo": [{"repo": "a", "tasks": tuned_tasks}]},
        "held_out": {"per_repo": [{"repo": "b", "tasks": held_tasks}]},
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_an_adequate_fully_accounted_run_passes():
    result = check_sample_adequacy(_run(8, 5, 3, 0), min_tasks=3)
    assert result["passed"] is True
    assert _names(result) == ["run_scored", "enough_tasks", "all_tasks_decided"]
    assert result["tasks"] == 8 and result["decided"] == 8


def test_too_few_tasks_fails_enough_tasks():
    result = check_sample_adequacy(_run(2, 1, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_tasks"]
    assert result["tasks"] == 2


def test_the_task_bound_is_inclusive():
    assert check_sample_adequacy(_run(3, 2, 1, 0), min_tasks=3)["passed"] is True
    assert check_sample_adequacy(_run(2, 1, 1, 0), min_tasks=3)["passed"] is False


def test_min_tasks_is_configurable():
    run = _run(5, 3, 2, 0)
    assert check_sample_adequacy(run, min_tasks=5)["passed"] is True
    assert check_sample_adequacy(run, min_tasks=6)["passed"] is False


def test_min_tasks_below_one_accepts_any_scored_run():
    # A non-positive min_tasks has defined behaviour: any positive, fully-decided task total passes
    # enough_tasks (there is no lower bar), but a zero-task run still fails run_scored.
    assert check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=0)["passed"] is True
    assert check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=-5)["passed"] is True
    zero = check_sample_adequacy(_run(0, 0, 0, 0), min_tasks=0)
    assert zero["passed"] is False and "run_scored" in failed_checks(zero)


def test_a_missing_tally_fails_all_tasks_decided():
    # No tally at all -> the run cannot show every task was decided -> fail (not a silent pass).
    result = check_sample_adequacy(_run(5), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] is None


def test_non_finite_task_count_fails_closed():
    # json round-trips NaN/Infinity, so a degenerate artifact can carry a non-finite task count.
    # Infinity must not clear run_scored (inf > 0) or enough_tasks (inf >= min); a non-finite
    # total is treated as unavailable and both fail closed (mirrors #1457/#1465), with tasks None.
    for bad in (float("inf"), float("nan"), float("-inf")):
        result = check_sample_adequacy(_run(bad, 3, 2, 1), min_tasks=3)
        assert result["passed"] is False, bad
        assert result["tasks"] is None, bad
        assert {"run_scored", "enough_tasks"} <= set(failed_checks(result)), bad


def test_non_finite_tally_and_tasks_do_not_pass_the_gate():
    # A fully-degenerate artifact (Infinity task count AND a matching Infinity tally) must not
    # sign off adequacy via inf >= min and inf == inf; every check fails closed.
    result = check_sample_adequacy(
        {"per_repo": [{"tasks": float("inf"),
                       "tally": {"challenger": float("inf"), "baseline": 0, "tie": 0}}]},
        min_tasks=5,
    )
    assert result["passed"] is False
    assert set(_names(result)) == set(failed_checks(result))   # all three fail
    assert result["tasks"] is None


def test_a_tally_missing_a_key_fails_all_tasks_decided():
    result = check_sample_adequacy({"tasks": 5, "tally": {"challenger": 3, "tie": 0}}, min_tasks=3)
    assert result["passed"] is False
    assert "all_tasks_decided" in failed_checks(result)
    assert result["decided"] is None


def test_a_tally_that_omits_tasks_fails_all_tasks_decided():
    # 6 tasks reported, but the tally only decides 4 -> two tasks vanished.
    result = check_sample_adequacy(_run(6, 3, 1, 0), min_tasks=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["all_tasks_decided"]
    assert result["decided"] == 4


def test_a_multi_repo_run_sums_per_repo_tasks():
    result = check_sample_adequacy(_multi(2, 3, 4), min_tasks=5)
    assert result["tasks"] == 9
    # No tally on this synthetic multi-repo result, so accounting fails; the count is still summed.
    assert "all_tasks_decided" in failed_checks(result)
    result_with_tally = dict(_multi(2, 3, 4), tally={"challenger": 5, "baseline": 3, "tie": 1})
    assert check_sample_adequacy(result_with_tally, min_tasks=5)["passed"] is True


def test_a_generalization_run_sums_both_partitions():
    result = check_sample_adequacy(dict(_gen(4, 3), tally={"challenger": 4, "baseline": 2, "tie": 1}),
                                   min_tasks=6)
    assert result["tasks"] == 7
    assert result["passed"] is True


# --- a real multi-repo/generalization run reports its tally under per_repo, not top-level ------
# run_multi_replay / run_generalization_report emit no top-level `tally`; each per_repo entry
# carries its own. all_tasks_decided must sum those (as _total_tasks sums per-repo tasks) instead
# of only reading a top-level tally that real cross-repo runs never emit.


def _repo(tasks, ch, ba, ti):
    return {"repo": "r", "tasks": tasks, "tally": {"challenger": ch, "baseline": ba, "tie": ti}}


def test_generalization_partition_error_fails_run_scored():
    gen = {
        "tuned": {"error": "repo set test has no tuned repos to replay", "scored_repos": 0},
        "held_out": {"per_repo": [_repo(5, 4, 1, 0), _repo(7, 5, 1, 1)]},
        "generalization_gap": None,
    }
    result = check_sample_adequacy(gen, min_tasks=10)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)
    assert "tuned=" in next(c["detail"] for c in result["checks"] if c["name"] == "run_scored")


def test_generalization_per_repo_error_on_tuned_fails_run_scored():
    gen = {
        "tuned": {"per_repo": [{"repo": "bad", "error": "clone failed", "tasks": 0}]},
        "held_out": {"per_repo": [_repo(6, 4, 1, 1), _repo(6, 3, 2, 1)]},
        "generalization_gap": None,
    }
    result = check_sample_adequacy(gen, min_tasks=10)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_real_multi_repo_run_with_per_repo_tallies_is_adequate():
    result = check_sample_adequacy({"per_repo": [_repo(5, 4, 1, 0), _repo(5, 3, 1, 1)]}, min_tasks=6)
    assert result["tasks"] == 10 and result["decided"] == 10
    assert result["passed"] is True and "all_tasks_decided" not in failed_checks(result)


def test_real_generalization_run_with_per_repo_tallies_is_adequate():
    result = check_sample_adequacy({
        "tuned": {"per_repo": [_repo(4, 3, 1, 0)]},
        "held_out": {"per_repo": [_repo(3, 1, 1, 1)]},
        "generalization_gap": 0.1,
    }, min_tasks=6)
    assert result["tasks"] == 7 and result["decided"] == 7 and result["passed"] is True


def test_multi_repo_with_a_skipped_repo_is_fully_decided():
    # A skipped (zero-task) repo carries no tally and decides nothing; the scored repo's tasks are
    # still all accounted for, so decided == tasks over the run that actually scored.
    result = check_sample_adequacy(
        {"per_repo": [_repo(5, 4, 1, 0), {"repo": "b", "tasks": 0, "error": "too small"}]}, min_tasks=3)
    assert result["tasks"] == 5 and result["decided"] == 5 and result["passed"] is True


def test_multi_repo_undercounted_tally_fails_all_tasks_decided():
    # Correctness of the aggregate, not just "did not crash": a per_repo tally that decides fewer
    # tasks than the repo ran (a dropped task) must fail accounting, not pass.
    result = check_sample_adequacy({"per_repo": [_repo(5, 3, 1, 0)]}, min_tasks=3)  # tally sums 4 != 5
    assert result["decided"] == 4 and result["tasks"] == 5
    assert result["passed"] is False and "all_tasks_decided" in failed_checks(result)


def test_multi_repo_scored_entry_missing_tally_fails_closed():
    # A scored per_repo entry with no tally cannot be accounted for -> fail closed (decided None).
    result = check_sample_adequacy({"per_repo": [_repo(5, 4, 1, 0), {"repo": "b", "tasks": 3}]}, min_tasks=3)
    assert result["decided"] is None and "all_tasks_decided" in failed_checks(result)


def test_top_level_per_repo_is_not_double_counted_with_partitions():
    # An artifact that carries BOTH a top-level per_repo (the complete multi-repo list) and
    # tuned/held_out partition lists must count the tasks once, not sum both shapes. The
    # top-level list wins, mirroring the sibling gates (coverage, tally_integrity, ...).
    artifact = {
        "per_repo": [{"repo": "a", "tasks": 4}, {"repo": "b", "tasks": 3}],
        "tuned": {"per_repo": [{"repo": "a", "tasks": 4}]},
        "held_out": {"per_repo": [{"repo": "b", "tasks": 3}]},
        "tally": {"challenger": 4, "baseline": 2, "tie": 1},  # decides all 7 real tasks
    }
    result = check_sample_adequacy(artifact, min_tasks=6)
    assert result["tasks"] == 7                       # not 14 (double-counted)
    assert result["decided"] == 7
    assert "all_tasks_decided" not in failed_checks(result)
    assert result["passed"] is True


def test_a_multi_repo_run_with_a_malformed_entry_fails_run_scored():
    # A non-dict per-repo entry makes the total untrustworthy: fail run_scored, don't silently drop.
    for bad_per_repo in ([{"tasks": 4}, "oops"], [{"tasks": 4}, {"repo": "x"}], [{"tasks": 4}, {"tasks": "n"}]):
        result = check_sample_adequacy({"per_repo": bad_per_repo}, min_tasks=3)
        assert result["passed"] is False
        assert "run_scored" in failed_checks(result)
        assert result["tasks"] is None


def test_an_empty_per_repo_list_is_untrustworthy():
    result = check_sample_adequacy({"per_repo": []}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)
    assert result["tasks"] is None


def test_a_partition_missing_per_repo_entirely_fails_the_same_as_an_empty_one():
    # A held_out partition that never got populated (no per_repo, no error) carries the same
    # real-world meaning as an explicit `per_repo: []` -- both must fail closed identically,
    # not be silently dropped from consideration.
    tuned = {"per_repo": [{"repo": "a", "tasks": 5,
                            "tally": {"challenger": 2, "baseline": 2, "tie": 1}}]}
    missing_key = check_sample_adequacy({"tuned": tuned, "held_out": {}}, min_tasks=3)
    explicit_empty = check_sample_adequacy(
        {"tuned": tuned, "held_out": {"per_repo": []}}, min_tasks=3)
    assert missing_key["passed"] is False
    assert missing_key["tasks"] is None
    assert missing_key["passed"] == explicit_empty["passed"]
    assert missing_key["tasks"] == explicit_empty["tasks"]


def test_an_errored_run_fails_run_scored():
    result = check_sample_adequacy({"error": "clone failed", "tasks": 0}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_zero_task_run_fails_run_scored():
    result = check_sample_adequacy(_run(0, 0, 0, 0), min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_run_with_no_task_information_fails_gracefully():
    result = check_sample_adequacy({"composite_mean": 0.6}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)
    assert result["tasks"] is None


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_sample_adequacy(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["tasks"] is None


def test_non_numeric_top_level_tasks_do_not_crash():
    result = check_sample_adequacy({"tasks": "many"}, min_tasks=3)
    assert result["passed"] is False
    assert "run_scored" in failed_checks(result)


def test_a_non_dict_tally_is_treated_as_missing():
    result = check_sample_adequacy({"tasks": 5, "tally": "nope"}, min_tasks=3)
    assert result["passed"] is False
    assert "all_tasks_decided" in failed_checks(result)
    assert result["decided"] is None


def test_headline_reports_adequate_and_inadequate():
    assert "ADEQUATE" in sample_adequacy_headline(check_sample_adequacy(_run(8, 8, 0, 0), min_tasks=3))
    small = sample_adequacy_headline(check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=3))
    assert "INADEQUATE" in small
    # No bare "None" even when the task total is unknown.
    missing = sample_adequacy_headline(check_sample_adequacy({}, min_tasks=3))
    assert "None" not in missing
    assert DEFAULT_MIN_TASKS == 3


def test_headline_handles_a_result_with_no_checks():
    assert sample_adequacy_headline({}) == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline("not a dict") == "sample adequacy: no checks evaluated"
    assert sample_adequacy_headline({"checks": []}) == "sample adequacy: no checks evaluated"


# --- #701: checks hardening (resubmit of #703) ---------------------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "run_scored"}, "not a list",
    ({"name": "run_scored", "passed": False},),  # tuple, not list
    range(2),  # iterable but not a list
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "run_scored", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "run_scored", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "run_scored", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_sample_adequacy_headline_survives_non_list_checks():
    base = {"passed": False, "tasks": 0}
    for bad in _MALFORMED_CHECKS:
        assert sample_adequacy_headline({**base, "checks": bad}) == (
            "sample adequacy: no checks evaluated"
        ), bad


def test_sample_adequacy_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        line = sample_adequacy_headline({"checks": 42, "passed": False})
    assert line == "sample adequacy: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "run_scored", "passed": False},
        42,
        {"name": "enough_tasks", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.sample_adequacy"):
        assert failed_checks({"checks": checks}) == ["run_scored"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_sample_adequacy(_run(1, 1, 0, 0), min_tasks=3)) != []


def test_check_sample_adequacy_does_not_mutate_the_result():
    run = _run(8, 5, 3, 0)
    snapshot = copy.deepcopy(run)
    check_sample_adequacy(run)
    assert run == snapshot


# --- the CLI load_artifact must report a clean error, not a raw traceback (#1073) --------------
# load_artifact caught FileNotFoundError / JSONDecodeError / non-object, but a path that reaches
# open() and raises a non-FileNotFoundError OSError — a directory (IsADirectoryError) or an
# unreadable file (PermissionError) — escaped as a raw traceback. Each read-failure mode is now
# reported distinctly with exit code 2.


def test_load_artifact_reads_a_valid_object(tmp_path):
    path = tmp_path / "ok.json"
    path.write_text('{"tasks": 3}', encoding="utf-8")
    assert cli.load_artifact(str(path)) == {"tasks": 3}


def test_load_artifact_missing_file_still_reports_not_found(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.load_artifact(str(tmp_path / "missing.json"))
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not found" in err and "is a directory" not in err and "permission" not in err.lower()


def test_load_artifact_directory_path_exits_two_cleanly(tmp_path, capsys):
    # A directory reaches open() and raises IsADirectoryError (POSIX) or PermissionError (Windows) —
    # an OSError, not FileNotFoundError. It must surface as a clean exit(2) artifact-read error,
    # never a raw traceback and never mistaken for "not found" / "invalid JSON".
    d = tmp_path / "a_dir"
    d.mkdir()
    with pytest.raises(SystemExit) as exc:
        cli.load_artifact(str(d))
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "artifact" in err
    assert "not found" not in err and "not valid JSON" not in err and "JSON object" not in err
    if os.name == "posix":
        assert "is a directory" in err  # IsADirectoryError branch on POSIX (CI)


@pytest.mark.skipif(os.name != "posix", reason="POSIX file-mode permissions required")
def test_load_artifact_unreadable_file_exits_two_cleanly(tmp_path, capsys):
    # A real permission-denied file (os.chmod, not a mock): open() raises PermissionError (an
    # OSError). It must exit 2 with a permission message, not a raw traceback.
    locked = tmp_path / "locked.json"
    locked.write_text('{"tasks": 1}', encoding="utf-8")
    locked.chmod(0)
    if os.access(str(locked), os.R_OK):
        # Running as root (or a filesystem ignoring mode bits): the read isn't actually blocked.
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
        pytest.skip("cannot make a file unreadable in this environment (running as root?)")
    try:
        with pytest.raises(SystemExit) as exc:
            cli.load_artifact(str(locked))
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "permission denied" in err.lower() and "not found" not in err
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)  # let tmp_path cleanup remove it


def test_load_artifact_still_reports_bad_json_and_non_object(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.load_artifact(str(bad))
    assert "not valid JSON" in capsys.readouterr().err
    lst = tmp_path / "list.json"
    lst.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(SystemExit):
        cli.load_artifact(str(lst))
    assert "JSON object" in capsys.readouterr().err
