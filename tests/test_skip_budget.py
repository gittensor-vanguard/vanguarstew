"""Tests for the multi-repo skip-budget gate and its CLI (deterministic, offline)."""

import copy
import json
import logging
import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_budget import (  # noqa: E402
    DEFAULT_MAX_SKIP_RATE,
    DEFAULT_MIN_SCORED,
    _check_rows_list,
    check_skip_budget,
    failed_checks,
    skip_budget_headline,
)
from scripts import skip_budget as cli  # noqa: E402


def _multi(repos, scored, skipped=None, **extra):
    result = {"repos": repos, "scored_repos": scored, "composite_mean": 0.6}
    result["skipped"] = repos - scored if skipped is None else skipped
    result.update(extra)
    return result


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_well_covered_run_passes():
    result = check_skip_budget(_multi(8, 7), min_scored=3, max_skip_rate=0.25)  # skip 1/8 = 0.125
    assert result["passed"] is True
    assert _names(result) == ["multi_repo_accounting", "enough_scored", "skip_within_budget"]
    assert result["scored_repos"] == 7 and result["skipped"] == 1 and result["skip_rate"] == 0.125


def test_too_many_skipped_fails_skip_within_budget():
    result = check_skip_budget(_multi(6, 2), min_scored=1, max_skip_rate=0.25)  # skip 4/6 = 0.667
    assert result["passed"] is False
    assert failed_checks(result) == ["skip_within_budget"]
    assert result["skip_rate"] == 0.667


def test_too_few_scored_fails_enough_scored():
    result = check_skip_budget(_multi(3, 2), min_scored=3, max_skip_rate=0.5)  # only 2 scored
    assert result["passed"] is False
    assert "enough_scored" in failed_checks(result)


def test_the_skip_rate_bound_is_inclusive():
    assert check_skip_budget(_multi(4, 3), min_scored=1, max_skip_rate=0.25)["passed"] is True  # 0.25
    assert check_skip_budget(_multi(4, 2), min_scored=1, max_skip_rate=0.25)["passed"] is False  # 0.5


def test_a_full_run_with_no_skips_passes():
    result = check_skip_budget(_multi(5, 5), min_scored=3)
    assert result["passed"] is True
    assert result["skip_rate"] == 0.0 and result["skipped"] == 0


def test_thresholds_are_configurable():
    run = _multi(10, 7)                                     # 3 skipped, rate 0.3
    assert check_skip_budget(run, min_scored=7, max_skip_rate=0.3)["passed"] is True
    assert check_skip_budget(run, min_scored=8)["passed"] is False
    assert check_skip_budget(run, max_skip_rate=0.25)["passed"] is False


def test_a_single_repo_run_fails_multi_repo_accounting():
    # A single-repo artifact has no repos/scored_repos tally -> this gate does not apply -> fail.
    result = check_skip_budget({"composite_mean": 0.6, "tasks": 8})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None and result["skip_rate"] is None


def test_inconsistent_skipped_field_fails_accounting():
    # skipped that doesn't equal repos - scored is internally inconsistent -> untrustworthy.
    result = check_skip_budget({"repos": 8, "scored_repos": 6, "skipped": 0})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None


def test_a_consistent_skipped_field_is_accepted():
    result = check_skip_budget({"repos": 8, "scored_repos": 6, "skipped": 2}, min_scored=3,
                               max_skip_rate=0.25)
    assert result["passed"] is True
    assert result["skipped"] == 2 and result["skip_rate"] == 0.25


def test_scored_exceeding_repos_fails_accounting():
    result = check_skip_budget({"repos": 3, "scored_repos": 5})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_zero_repos_fails_accounting():
    result = check_skip_budget({"repos": 0, "scored_repos": 0})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)
    assert result["repos"] is None


def test_fractional_counts_are_rejected():
    # Repo counts come from len(...) and are always whole; a float like 7.0 is treated as malformed.
    for bad in ({"repos": 8.0, "scored_repos": 7}, {"repos": 8, "scored_repos": 7.0},
                {"repos": 8, "scored_repos": 6, "skipped": 2.0}):
        result = check_skip_budget(bad)
        assert result["passed"] is False
        assert "multi_repo_accounting" in failed_checks(result)
        assert result["repos"] is None


def test_boolean_counts_are_rejected():
    # bool is an int subclass; True must not be accepted as a count of 1.
    result = check_skip_budget({"repos": True, "scored_repos": True})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_malformed_or_non_dict_results_fail_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_skip_budget(bad)
        assert result["passed"] is False
        assert result["checks"]
        assert result["repos"] is None


def test_non_numeric_counts_do_not_crash():
    result = check_skip_budget({"repos": "eight", "scored_repos": None})
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_a_float_skip_rate_is_rounded():
    # 1/3 rounds to 0.333, not 0.3333333333333333, so the bound compares cleanly.
    assert check_skip_budget(_multi(3, 2), min_scored=1, max_skip_rate=0.4)["skip_rate"] == 0.333


# --- #839: checks row sanitization for skip budget headlines ------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "enough_scored"}, "not a list",
    ({"name": "enough_scored", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "enough_scored", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "enough_scored", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "enough_scored", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list(junk) == []
    assert any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "enough_scored", "passed": False},
        {"name": "skip_within_budget", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [valid[0], 42, {}, {"name": "enough_scored", "passed": 1}, valid[1]]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert _check_rows_list([{"name": "enough_scored", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_helpers_survive_a_non_list_checks_value():
    for bad_checks in ("garbage", 42, {"name": "x"}, None):
        assert failed_checks({"checks": bad_checks}) == []
        assert skip_budget_headline({"checks": bad_checks}) == "skip budget: no checks evaluated"


def test_skip_budget_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "enough_scored", "passed": False}, "oops"]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        line = skip_budget_headline({"checks": checks, "passed": False})
    assert line == "skip budget: UNDER-COVERED (1/1 checks failed: enough_scored)"
    assert any("checks[1] is str" in r.message for r in caplog.records)


def test_failed_checks_integration_with_check_rows_list(caplog):
    checks = [
        {"name": "enough_scored", "passed": False},
        "oops",
        {"name": "skip_within_budget", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.skip_budget"):
        assert failed_checks({"checks": checks}) == ["enough_scored"]
    assert any("checks[1] is str" in r.message for r in caplog.records)


def test_headline_reports_covered_and_under_covered():
    assert "COVERED" in skip_budget_headline(check_skip_budget(_multi(8, 8), min_scored=3))
    under = skip_budget_headline(check_skip_budget(_multi(6, 1), min_scored=3))
    assert "UNDER-COVERED" in under
    # No bare "None" even when the accounting is missing.
    missing = skip_budget_headline(check_skip_budget({}))
    assert "None" not in missing
    assert DEFAULT_MIN_SCORED == 3 and DEFAULT_MAX_SKIP_RATE == 0.25


def test_headline_handles_a_result_with_no_checks():
    assert skip_budget_headline({}) == "skip budget: no checks evaluated"
    assert skip_budget_headline("not a dict") == "skip budget: no checks evaluated"
    assert skip_budget_headline({"checks": []}) == "skip budget: no checks evaluated"


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_skip_budget(_multi(6, 1), min_scored=3)) != []


def test_check_skip_budget_does_not_mutate_the_result():
    run = _multi(8, 7)
    snapshot = copy.deepcopy(run)
    check_skip_budget(run)
    assert run == snapshot


# --- generalization: sum tuned/held_out tallies (mirrors skip_share) --------------------


def _gen(tuned, held_out, gap=0.1):
    return {"tuned": tuned, "held_out": held_out, "generalization_gap": gap}


def test_generalization_well_covered_run_passes():
    gen = _gen(
        {"repos": 8, "scored_repos": 7, "skipped": 1},
        {"repos": 6, "scored_repos": 5, "skipped": 1},
    )
    result = check_skip_budget(gen, min_scored=3, max_skip_rate=0.25)
    assert result["passed"] is True
    assert result["repos"] == 14 and result["scored_repos"] == 12
    assert result["skipped"] == 2 and result["skip_rate"] == round(2 / 14, 3)


def test_generalization_held_out_skip_blowout_fails():
    gen = _gen(
        {"repos": 8, "scored_repos": 7, "skipped": 1},
        {"repos": 6, "scored_repos": 2, "skipped": 4},
    )
    result = check_skip_budget(gen, min_scored=3, max_skip_rate=0.25)
    assert result["passed"] is False
    assert "skip_within_budget" in failed_checks(result)
    assert result["skip_rate"] == round(5 / 14, 3)


def test_generalization_agrees_with_skip_share_overall():
    from benchmark.skip_share import summarize_skip_share
    gen = _gen(
        {"repos": 8, "scored_repos": 7, "skipped": 1},
        {"repos": 6, "scored_repos": 2, "skipped": 4},
    )
    result = check_skip_budget(gen, min_scored=1, max_skip_rate=0.5)
    share = summarize_skip_share(gen)
    assert result["repos"] == share["repos"]
    assert result["scored_repos"] == share["scored_repos"]
    assert result["skip_rate"] == share["skip_share"]


def test_generalization_without_partition_counts_fails_accounting():
    gen = {"tuned": {"composite_mean": 0.6}, "held_out": {}, "generalization_gap": 0.1}
    result = check_skip_budget(gen)
    assert result["passed"] is False
    assert "multi_repo_accounting" in failed_checks(result)


def test_non_generalization_unchanged():
    result = check_skip_budget(_multi(8, 7), min_scored=3)
    assert result["passed"] is True
    assert result["repos"] == 8


# --- CLI ---

def _write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_returns_zero_for_a_covered_run(tmp_path, capsys):
    path = _write(tmp_path, "run.json", _multi(8, 7))
    assert cli.run([path, "--strict"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["passed"] is True


def test_cli_strict_returns_one_for_an_under_covered_run(tmp_path, capsys):
    path = _write(tmp_path, "run.json", _multi(6, 1))
    assert cli.run([path, "--strict"]) == 1
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_cli_without_strict_returns_zero_even_when_failing(tmp_path, capsys):
    path = _write(tmp_path, "run.json", _multi(6, 1))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["passed"] is False


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory path raises IsADirectoryError inside open(); the CLI must report it cleanly and
    # exit 2 (SystemExit(2)), not dump a raw traceback (mirrors generalization_gate #1446).
    with pytest.raises(SystemExit) as exc:
        cli.run([str(tmp_path)])
    assert exc.value.code == 2
    assert "directory" in capsys.readouterr().err


def test_cli_unreadable_file_exits_two(capsys):
    # An unreadable file raises PermissionError; the CLI reports it cleanly and exits 2.
    with patch("builtins.open", side_effect=PermissionError("denied")):
        with pytest.raises(SystemExit) as exc:
            cli.run(["locked.json"])
    assert exc.value.code == 2
    assert "not readable" in capsys.readouterr().err


def test_cli_generic_os_error_exits_two(capsys):
    # Any other OSError (e.g. an I/O error) is reported cleanly with its message, not a traceback.
    with patch("builtins.open", side_effect=OSError("I/O error")):
        with pytest.raises(SystemExit) as exc:
            cli.run(["flaky.json"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "I/O error" in err


def test_cli_honours_threshold_flags(tmp_path):
    path = _write(tmp_path, "run.json", _multi(10, 7))          # rate 0.3
    assert cli.run([path, "--strict", "--max-skip-rate", "0.3"]) == 0
    assert cli.run([path, "--strict", "--max-skip-rate", "0.25"]) == 1
    assert cli.run([path, "--strict", "--min-scored", "8"]) == 1


def test_cli_rejects_a_missing_file(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.run([str(tmp_path / "nope.json")])
    assert exc.value.code == 2


def test_cli_rejects_malformed_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.run([str(path)])
    assert exc.value.code == 2


def test_cli_rejects_a_non_object_artifact(tmp_path):
    path = _write(tmp_path, "list.json", [1, 2, 3])
    with pytest.raises(SystemExit) as exc:
        cli.run([str(path)])
    assert exc.value.code == 2


def test_cli_main_exits_with_the_return_code(tmp_path, monkeypatch):
    path = _write(tmp_path, "run.json", _multi(6, 1))
    monkeypatch.setattr(sys, "argv", ["skip_budget", path, "--strict"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
