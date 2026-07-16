"""Tests for run-clean gate and CLI (deterministic, offline)."""

import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from benchmark.run_clean import (  # noqa: E402
    _check_rows_list,
    _findings_list,
    check_run_clean,
    failed_checks,
    run_clean_headline,
)
from scripts import run_clean as cli  # noqa: E402


def _multi(*repos):
    return {
        "repos": len(repos),
        "scored_repos": len(repos),
        "composite_mean": 0.6,
        "per_repo": [{"repo": r, "tasks": 3, "composite_mean": 0.6} for r in repos],
    }


def test_clean_multi_repo_passes():
    result = check_run_clean(_multi("a", "b"))
    assert result["passed"] is True
    assert failed_checks(result) == []


def test_top_level_error_fails():
    result = check_run_clean({"error": "clone failed", "tasks": 0})
    assert result["passed"] is False
    assert failed_checks(result) == ["no_errors"]


def test_per_repo_error_fails():
    art = _multi("ok")
    art["per_repo"].append({"repo": "bad", "error": "freeze failed", "tasks": 0})
    result = check_run_clean(art)
    assert result["passed"] is False


def test_partition_error_in_generalization():
    art = {
        "tuned": _multi("a"),
        "held_out": {"error": "empty", "per_repo": []},
        "generalization_gap": None,
    }
    result = check_run_clean(art)
    assert result["passed"] is False


def test_malformed_string_per_repo_row_fails():
    # A per_repo row that is itself a non-empty string is a malformed/corrupt entry, not a
    # well-formed result dict — it must fail closed (aligned with acceptance._partition_error),
    # not slip through as clean.
    art = _multi("ok")
    art["per_repo"].append("corrupt row")
    result = check_run_clean(art)
    assert result["passed"] is False
    assert any("malformed row" in f for f in result["findings"])


def test_malformed_string_per_repo_row_fails_under_generalization():
    tuned = _multi("a")
    tuned["per_repo"].append("boom")
    art = {"tuned": tuned, "held_out": _multi("b"), "generalization_gap": 0.0}
    result = check_run_clean(art)
    assert result["passed"] is False
    assert any("tuned.per_repo" in f and "malformed row" in f for f in result["findings"])


def test_empty_string_and_non_str_non_dict_per_repo_rows_are_ignored():
    # Empty/whitespace string rows and non-dict/non-string rows carry no error signal and are
    # ignored (same as acceptance._partition_error), so an otherwise-clean run still passes.
    art = _multi("ok")
    art["per_repo"] += ["", "   ", 42, None, ["x"]]
    result = check_run_clean(art)
    assert result["passed"] is True
    assert result["findings"] == []


def test_headline():
    assert "OK" in run_clean_headline(check_run_clean(_multi("a")))
    assert "ERRORS" in run_clean_headline(check_run_clean({"error": "x"}))


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli_strict(tmp_artifact, capsys):
    clean = tmp_artifact("clean.json", _multi("a"))
    dirty = tmp_artifact("dirty.json", {"error": "fail"})
    assert cli.run([clean, "--strict"]) == 0
    assert cli.run([dirty, "--strict"]) == 1


def test_cli_without_strict_exits_zero_on_error(tmp_artifact):
    path = tmp_artifact("dirty.json", {"error": "fail"})
    assert cli.run([path]) == 0


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory path raises IsADirectoryError inside open(); the CLI must report it cleanly and
    # exit 2, not dump a raw traceback (mirrors generalization_gate #1446 / objective_integrity #1377).
    assert cli.run([str(tmp_path)]) == 2
    assert "directory" in capsys.readouterr().err


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_run_clean({"error": "x"})) == ["no_errors"]
    assert failed_checks(check_run_clean(_multi("a"))) == []


# --- #846: checks row sanitization for failed_checks helper -------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "no_errors"}, "not a list",
    ({"name": "no_errors", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "no_errors", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "no_errors", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "no_errors", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "no_errors", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_rejects_empty_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list([{"name": "", "passed": False}]) == []
    assert any("name is empty str" in r.message for r in caplog.records)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "no_errors", "passed": False},
        {"name": "other", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": "", "passed": False},
        {"name": 99, "passed": False},
        {"name": "no_errors", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_accepts_native_bool_values():
    rows = [
        {"name": "no_errors", "passed": True},
        {"name": "other", "passed": False},
    ]
    assert _check_rows_list(rows) == rows


def test_check_rows_list_accepts_numpy_bool_when_available():
    if not HAS_NUMPY:
        pytest.skip("numpy not installed")
    rows = [{"name": "no_errors", "passed": np.bool_(True)}]
    assert _check_rows_list(rows) == rows


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _check_rows_list([{"name": "no_errors", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "no_errors"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "", "passed": False}],
        [{"name": "no_errors", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_integration_with_check_rows_list(caplog):
    checks = [
        {"name": "no_errors", "passed": False},
        42,
        {"name": "other", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert failed_checks({"checks": checks}) == ["no_errors"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


# --- #1219: run_clean_headline must not crash on a truthy non-list findings ---


def test_run_clean_headline_survives_a_non_list_findings():
    # Before #1219: `result.get("findings") or []` let a truthy non-list through, so len(42)
    # raised TypeError and aborted the CLI headline path. It must read as 0 findings instead.
    assert run_clean_headline({"passed": False, "findings": 42}) == "run clean: ERRORS (0 finding(s))"
    for bad in (42, 3.14, True, {"top-level error": "x"}, "boom", range(2)):
        assert run_clean_headline({"passed": False, "findings": bad}) == "run clean: ERRORS (0 finding(s))", bad


def test_run_clean_headline_counts_a_real_findings_list():
    out = run_clean_headline({"passed": False, "findings": ["a error", "b error", "c error"]})
    assert out == "run clean: ERRORS (3 finding(s))"


def test_findings_list_treats_non_list_as_empty_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _findings_list(42) == []
    assert any("findings is int, not a list" in r.message for r in caplog.records)


def test_findings_list_absent_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.run_clean"):
        assert _findings_list(None) == []
        assert _findings_list([]) == []
    assert not caplog.records


def test_findings_list_passes_a_real_list_through():
    findings = ["top-level error: 'boom'", "tuned error: 'x'"]
    assert _findings_list(findings) == findings
