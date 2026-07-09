"""Tests for the pairwise-judge robustness gate (deterministic, offline)."""

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

from benchmark.judge_gate import (  # noqa: E402
    DEFAULT_MAX_DISAGREEMENT,
    _check_rows_list,
    check_judge,
    failed_checks,
    judge_headline,
)


def _result(dual_order=True, dual_tasks=5, disagreement=0.1, stats_tasks=None):
    r = {
        "judge_dual_order": dual_order,
        "judge_report": {"disagreement_rate": disagreement, "dual_order_tasks": dual_tasks},
    }
    if stats_tasks is not None:
        r["judge_order_stats"] = {"dual_order_tasks": stats_tasks}
    return r


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_robust_run_passes():
    result = check_judge(_result(dual_order=True, dual_tasks=5, disagreement=0.1))
    assert result["passed"] is True
    assert _names(result) == ["dual_order_judging", "enough_dual_order_tasks", "low_disagreement"]
    assert result["dual_order"] is True and result["dual_order_tasks"] == 5
    assert result["disagreement_rate"] == 0.1


def test_single_order_run_fails_dual_order_check():
    result = check_judge(_result(dual_order=False))
    assert result["passed"] is False
    assert "dual_order_judging" in failed_checks(result)


def test_high_disagreement_is_shaky():
    result = check_judge(_result(disagreement=0.5), max_disagreement=0.3)
    assert result["passed"] is False
    assert failed_checks(result) == ["low_disagreement"]


def test_too_few_dual_order_tasks_fails():
    result = check_judge(_result(dual_tasks=1), min_dual_order_tasks=2)
    assert result["passed"] is False
    assert "enough_dual_order_tasks" in failed_checks(result)


def test_dual_order_tasks_falls_back_to_judge_order_stats():
    # judge_report lacks the count; it is read from judge_order_stats instead.
    r = {"judge_dual_order": True, "judge_report": {"disagreement_rate": 0.1},
         "judge_order_stats": {"dual_order_tasks": 4}}
    result = check_judge(r)
    assert result["dual_order_tasks"] == 4 and result["passed"] is True


def test_disagreement_bound_is_inclusive():
    assert check_judge(_result(disagreement=0.3), max_disagreement=0.3)["passed"] is True
    assert check_judge(_result(disagreement=0.31), max_disagreement=0.3)["passed"] is False


def test_thresholds_are_configurable():
    run = _result(dual_tasks=3, disagreement=0.25)
    assert check_judge(run, max_disagreement=0.3, min_dual_order_tasks=3)["passed"] is True
    assert check_judge(run, max_disagreement=0.2)["passed"] is False
    assert check_judge(run, min_dual_order_tasks=4)["passed"] is False


def test_missing_disagreement_rate_fails_low_disagreement():
    r = {"judge_dual_order": True, "judge_report": {"dual_order_tasks": 5}}
    result = check_judge(r)
    assert "low_disagreement" in failed_checks(result)
    assert result["disagreement_rate"] is None


def test_malformed_or_non_dict_result_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_judge(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["dual_order"] is False and result["dual_order_tasks"] is None


def test_non_numeric_fields_do_not_crash():
    weird = {"judge_dual_order": "yes", "judge_report": {"disagreement_rate": "low",
             "dual_order_tasks": "many"}}
    result = check_judge(weird)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }


def test_headline_reports_robust_and_shaky():
    assert "ROBUST" in judge_headline(check_judge(_result()))
    shaky = judge_headline(check_judge(_result(disagreement=0.9)))
    assert "SHAKY" in shaky and "low_disagreement" in shaky
    assert judge_headline({}) == "judge: no checks evaluated"
    assert DEFAULT_MAX_DISAGREEMENT == 0.3


# --- #793: checks row sanitization for judge gate headlines ----------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "dual_order_judging"}, "not a list",
    ({"name": "dual_order_judging", "passed": False},),  # tuple, not list
    range(2),  # iterable but not a list
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "dual_order_judging", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "dual_order_judging", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "dual_order_judging", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"name": "dual_order_judging"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "dual_order_judging", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "dual_order_judging", "passed": False},
        {"name": "low_disagreement", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": "", "passed": False},
        {"name": 99, "passed": False},
        {"name": "dual_order_judging", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_accepts_native_bool_values():
    rows = [
        {"name": "dual_order_judging", "passed": True},
        {"name": "low_disagreement", "passed": False},
    ]
    assert _check_rows_list(rows) == rows


def test_check_rows_list_rejects_empty_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"name": "", "passed": False}]) == []
    assert any("name is empty str" in r.message for r in caplog.records)


def test_check_rows_list_accepts_numpy_bool_when_available():
    np = pytest.importorskip("numpy")
    for factory in (np.bool_, np.bool8):
        rows = [{"name": "dual_order_judging", "passed": factory(True)}]
        assert _check_rows_list(rows) == rows


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"name": "dual_order_judging", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_check_rows_list_rejects_non_bool_passed_values(caplog):
    class AlmostBool:
        def __bool__(self):
            return True

    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert _check_rows_list([{"name": "dual_order_judging", "passed": AlmostBool()}]) == []
        assert _check_rows_list([{"name": "dual_order_judging", "passed": "true"}]) == []
    messages = [r.message for r in caplog.records]
    assert any("passed is AlmostBool" in m for m in messages)
    assert any("passed is str" in m for m in messages)


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    shaky = check_judge(_result(dual_order=False))
    assert failed_checks(shaky) == ["dual_order_judging"]
    assert failed_checks(check_judge(_result())) == []


def test_judge_headline_survives_non_list_checks():
    base = {"passed": False, "dual_order_tasks": 0, "disagreement_rate": 0.5}
    for bad in _MALFORMED_CHECKS:
        assert judge_headline({**base, "checks": bad}) == "judge: no checks evaluated", bad


def test_judge_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "dual_order_judging"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "", "passed": False}],
        [{"name": "dual_order_judging", "passed": 1}],
    ):
        assert judge_headline({"checks": checks, "passed": False}) == "judge: no checks evaluated"


def test_judge_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "dual_order_judging", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": checks, "passed": False})
    assert line == "judge: SHAKY (1/1 checks failed: dual_order_judging)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_judge_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": 42, "passed": False})
    assert line == "judge: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_judge_headline_ignores_unsanitized_rows_in_denominator(caplog):
    checks = [
        {"name": "dual_order_judging", "passed": False},
        {"name": "", "passed": False},
        {"name": "low_disagreement", "passed": 1},
        42,
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        line = judge_headline({"checks": checks, "passed": False})
    assert line == "judge: SHAKY (1/1 checks failed: dual_order_judging)"
    assert any("name is empty str" in r.message for r in caplog.records)
    assert any("passed is int" in r.message for r in caplog.records)
    assert any("checks[3] is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "dual_order_judging"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "", "passed": False}],
        [{"name": "dual_order_judging", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_integration_with_check_rows_list(caplog):
    checks = [
        {"name": "dual_order_judging", "passed": False},
        42,
        {"name": "low_disagreement", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.judge_gate"):
        assert failed_checks({"checks": checks}) == ["dual_order_judging"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_every_check_reported_even_when_all_fail():
    result = check_judge({"judge_dual_order": False, "judge_report": {"disagreement_rate": 0.9}})
    assert len(result["checks"]) == 3
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }


def test_judge_report_dual_order_tasks_preferred_over_stats():
    # When both sources carry the count, judge_report (the canonical summary) wins.
    r = {"judge_dual_order": True,
         "judge_report": {"disagreement_rate": 0.1, "dual_order_tasks": 6},
         "judge_order_stats": {"dual_order_tasks": 99}}
    assert check_judge(r)["dual_order_tasks"] == 6


def test_a_realistic_shaky_run_names_all_failures():
    # Single-order, one task, high disagreement: every criterion fails and is reported.
    r = {"judge_dual_order": False,
         "judge_report": {"disagreement_rate": 0.6, "dual_order_tasks": 1}}
    result = check_judge(r, max_disagreement=0.3, min_dual_order_tasks=2)
    assert result["passed"] is False
    assert set(failed_checks(result)) == {
        "dual_order_judging", "enough_dual_order_tasks", "low_disagreement",
    }
    assert "SHAKY" in judge_headline(result)


def test_check_judge_does_not_mutate_the_result():
    run = _result()
    snapshot = copy.deepcopy(run)
    check_judge(run)
    assert run == snapshot


# --- CLI entry point: clean errors instead of tracebacks (#922) ---------------------------


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.judge_gate", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _run_main_in_process(monkeypatch, argv):
    import scripts.judge_gate as judge_gate_cli

    monkeypatch.setattr(sys, "argv", ["scripts.judge_gate", *argv])
    with pytest.raises(SystemExit) as excinfo:
        judge_gate_cli.main()
    return excinfo.value.code


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the FileNotFoundError message itself, naming the offending path
    assert "No such file or directory" in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    bad = _write(tmp_path / "bad.json", [1, 2, 3])
    result = _run_cli(bad)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # load_artifact's ValueError message, naming the offending path
    assert "must be a JSON object" in result.stderr
    assert bad in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(invalid))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    # the JSONDecodeError message with its parse position
    assert "Expecting property name enclosed in double quotes" in result.stderr
    assert "line 1" in result.stderr


def test_cli_reports_a_clean_error_for_a_directory_path(tmp_path):
    # IsADirectoryError is an OSError; end-to-end proof the guard covers the family even
    # when the suite runs as root (a chmod-000 fixture would be readable to root).
    unreadable = tmp_path / "a-directory"
    unreadable.mkdir()
    result = _run_cli(str(unreadable))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "Is a directory" in result.stderr
    assert str(unreadable) in result.stderr


def test_cli_reports_a_clean_error_for_a_permission_denied_file(tmp_path, monkeypatch, capsys):
    # In-process, so it holds under any uid (root reads chmod-000 files, so a filesystem
    # fixture cannot force EACCES deterministically): PermissionError must surface as the
    # one-line OSError message and a clean exit 1, never a traceback.
    import scripts.judge_gate as judge_gate_cli

    denied = str(tmp_path / "denied.json")

    def _deny(path):
        raise PermissionError(13, "Permission denied", denied)

    monkeypatch.setattr(judge_gate_cli, "load_artifact", _deny)
    code = _run_main_in_process(monkeypatch, [denied])
    assert code == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err
    assert denied in err


def test_cli_reports_a_clean_error_when_the_gate_check_itself_fails(tmp_path, monkeypatch, capsys):
    # The guard is not just around loading: if the gate evaluation blows up on artifact
    # content, the CLI must still exit 1 with a one-line error instead of a traceback.
    import scripts.judge_gate as judge_gate_cli

    good = _write(tmp_path / "good.json", _result())

    def _boom(artifact, max_disagreement, min_dual_order_tasks):
        raise TypeError("unhashable artifact content")

    monkeypatch.setattr(judge_gate_cli, "check_judge", _boom)
    code = _run_main_in_process(monkeypatch, [good])
    assert code == 1
    err = capsys.readouterr().err
    assert "cannot evaluate artifact" in err
    assert "unhashable artifact content" in err


def test_cli_still_gates_a_well_formed_artifact(tmp_path):
    robust = _write(tmp_path / "robust.json", _result(dual_order=True, dual_tasks=5, disagreement=0.1))
    result = _run_cli(robust)
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    summary = json.loads(result.stdout)
    assert summary["passed"] is True
    assert "[PASS]" in result.stderr


def test_cli_strict_exit_comes_from_the_gating_branch(tmp_path):
    # The error guards must not swallow or fake the --strict gating path. Prove the exit 1
    # originates from the gating branch: the full evaluation completed (headline + FAIL rows
    # on stderr, parseable summary on stdout with passed=false), and no loader/evaluation
    # error message appears.
    shaky = _write(tmp_path / "shaky.json",
                   {"judge_dual_order": False,
                    "judge_report": {"disagreement_rate": 0.6, "dual_order_tasks": 1}})
    result = _run_cli(shaky, "--strict")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "[FAIL]" in result.stderr
    summary = json.loads(result.stdout)
    assert summary["passed"] is False
    assert "cannot evaluate artifact" not in result.stderr
    assert "No such file or directory" not in result.stderr


def test_cli_without_strict_exits_zero_on_a_shaky_run(tmp_path):
    # Same shaky artifact, no --strict: the run reports and exits 0, confirming exit 1
    # above is the flag's doing rather than any error path.
    shaky = _write(tmp_path / "shaky.json",
                   {"judge_dual_order": False,
                    "judge_report": {"disagreement_rate": 0.6, "dual_order_tasks": 1}})
    result = _run_cli(shaky)
    assert result.returncode == 0
    assert "[FAIL]" in result.stderr
