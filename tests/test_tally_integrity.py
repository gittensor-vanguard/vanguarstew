"""Tests for the judge tally integrity gate (deterministic, offline)."""

import copy
import errno
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.tally_integrity as tally_integrity_cli  # noqa: E402
from benchmark.tally_integrity import (  # noqa: E402
    _check_rows_list,
    _count_row_winners,
    _integrity_slices,
    _tally_counts,
    check_tally_integrity,
    failed_checks,
    integrity_headline,
)


def _rows(challenger=2, baseline=1, tie=0):
    return (
        [{"winner": "challenger"}] * challenger
        + [{"winner": "baseline"}] * baseline
        + [{"winner": "tie"}] * tie
    )


def _slice(tasks=3, challenger=2, baseline=1, tie=0, margin=None, rows=None):
    tally = {"challenger": challenger, "baseline": baseline, "tie": tie}
    if rows is None:
        rows = _rows(challenger, baseline, tie)
    art = {"tasks": tasks, "tally": tally, "rows": rows}
    if margin is not False:
        art["decisive_margin"] = margin if margin is not None else challenger - baseline
    return art


def _artifact(**kwargs):
    return copy.deepcopy(_slice(**kwargs))


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_single_repo_passes():
    result = check_tally_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "tally_present", "tasks_reported", "tally_sums_to_tasks",
        "rows_match_tasks", "row_winners_match_tally", "decisive_margin_matches",
    ]


def test_tally_sum_mismatch_fails():
    art = _artifact()
    art["tally"]["challenger"] = 99
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_row_count_mismatch_fails():
    art = _artifact()
    art["rows"] = art["rows"][:-1]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "rows_match_tasks" in failed_checks(result)


def test_row_winners_mismatch_fails():
    art = _artifact()
    art["rows"][0]["winner"] = "baseline"
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "row_winners_match_tally" in failed_checks(result)


def test_decisive_margin_mismatch_fails():
    art = _artifact(margin=99)
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


def test_decisive_margin_near_miss_that_truncates_correctly_still_fails():
    # #1975: a corrupted margin that merely truncates to the right integer (int(1.999) == 1)
    # must not false-pass as "matches" -- the check compares the exact value, not a truncated
    # one. Same for a negative margin, since int() truncates toward zero, not floor.
    art = _artifact(tasks=9, challenger=5, baseline=4, margin=1.999)
    result = check_tally_integrity(art)
    assert "decisive_margin_matches" in failed_checks(result)

    art_negative = _artifact(tasks=7, challenger=3, baseline=4, margin=-1.9)
    result_negative = check_tally_integrity(art_negative)
    assert "decisive_margin_matches" in failed_checks(result_negative)


def test_decisive_margin_exact_float_equal_to_int_still_matches():
    # Control: a float that is genuinely equal to the expected int (not merely truncating to
    # it) must still pass -- the fix must not become stricter than exact-value equality.
    art = _artifact(tasks=9, challenger=5, baseline=4, margin=1.0)
    result = check_tally_integrity(art)
    assert "decisive_margin_matches" not in failed_checks(result)


def test_missing_tally_fails_tally_present():
    art = _artifact()
    del art["tally"]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tally_present" in failed_checks(result)
    assert "tally_sums_to_tasks" in failed_checks(result)


def test_missing_tasks_fails_tasks_reported():
    art = _artifact()
    del art["tasks"]
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "tasks_reported" in failed_checks(result)


def test_zero_tasks_slice_is_not_selected():
    result = check_tally_integrity({"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_zero_task_slice_with_empty_rows_is_consistent():
    # A real run_replay zero-task slice emits rows: [] (an EMPTY list, not an absent key). The
    # recount of [] equals the all-zero tally, so row_winners_match_tally must be True and the
    # artifact CONSISTENT. An empty rows list must not be conflated with a missing one -- the
    # check used `and rows:` (empty list is falsy) where its sibling rows_match_tasks correctly
    # uses `rows is not None`.
    art = {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0},
           "rows": [], "decisive_margin": 0}
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert failed_checks(result) == []
    row_check = next(c for c in result["checks"] if c["name"] == "row_winners_match_tally")
    assert row_check["passed"] is True


def test_non_finite_tally_count_fails_instead_of_raising():
    # Previously OverflowError from int(float("inf")) in _tally_counts. A NaN/Infinity count
    # survives a JSON save/load round trip but is not a usable count -- flag it, don't crash.
    art = _artifact()
    art["tally"]["challenger"] = float("inf")
    result = check_tally_integrity(art)          # must not raise
    assert result["passed"] is False
    assert "tally_present" in failed_checks(result)


def test_non_finite_tasks_fails_tasks_reported_instead_of_raising():
    # Previously ValueError from int(float("nan")) while selecting/checking the slice.
    art = _artifact()
    art["tasks"] = float("nan")
    result = check_tally_integrity(art)          # must not raise
    assert result["passed"] is False
    assert "tasks_reported" in failed_checks(result)


def test_non_finite_decisive_margin_fails_instead_of_raising():
    # Previously OverflowError from int(float("inf")) in the decisive_margin check.
    art = _artifact()
    art["decisive_margin"] = float("inf")
    result = check_tally_integrity(art)          # must not raise
    assert result["passed"] is False
    assert "decisive_margin_matches" in failed_checks(result)


def test_non_finite_numeric_fields_never_raise_for_any_variant():
    # NaN, +/-Infinity, and an int too large for a float all survive a JSON round trip and
    # would crash int()/isfinite; none may raise, in a single-repo or a per_repo slice.
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        for field in ("challenger", "baseline", "tie"):
            art = _artifact()
            art["tally"][field] = bad
            assert isinstance(check_tally_integrity(art)["passed"], bool), (field, bad)

        art = _artifact()
        art["tasks"] = bad
        assert isinstance(check_tally_integrity(art)["passed"], bool), ("tasks", bad)

        art = _artifact()
        art["decisive_margin"] = bad
        assert isinstance(check_tally_integrity(art)["passed"], bool), ("margin", bad)

        per_repo = {"per_repo": [{"tasks": bad,
                                  "tally": {"challenger": 1, "baseline": 0, "tie": 0},
                                  "rows": []}]}
        assert isinstance(check_tally_integrity(per_repo)["passed"], bool), ("per_repo", bad)


def test_slice_without_rows_skips_row_checks():
    entry = {
        "tasks": 3,
        "tally": {"challenger": 2, "baseline": 1, "tie": 0},
        "decisive_margin": 1,
    }
    result = check_tally_integrity({"per_repo": [entry]})
    assert result["passed"] is True
    assert "rows_match_tasks" not in _names(result)


def test_slice_without_decisive_margin_skips_margin_check():
    art = _artifact(margin=False)
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "decisive_margin_matches" not in _names(result)


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_tally_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_tally_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(tasks=2, challenger=1, baseline=1, tie=0),
            {"tasks": 0, "tally": {"challenger": 0, "baseline": 0, "tie": 0}},
            _artifact(tasks=1, challenger=1, baseline=0, tie=0),
        ],
    }
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "repo-0:row_winners_match_tally" in _names(result)
    assert "repo-2:decisive_margin_matches" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.1,
        "tuned": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=2, challenger=2, baseline=0, tie=0)],
        },
        "held_out": {
            "scored_repos": 1,
            "per_repo": [_artifact(tasks=1, challenger=0, baseline=1, tie=0)],
        },
    }
    result = check_tally_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:tally_sums_to_tasks" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_per_repo_without_scored_repos_is_checked():
    held = _artifact()
    held["scored_repos"] = 1
    bad = _artifact(tasks=3, challenger=2, baseline=1, tie=0)
    bad["tally"] = {"challenger": 0, "baseline": 3, "tie": 0}
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [bad]},
        "held_out": held,
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert any(name.startswith("tuned:repo-0:") for name in failed_checks(result))


def test_tally_counts_rejects_malformed_values():
    assert _tally_counts({"challenger": 1, "baseline": "x", "tie": 0}) is None
    assert _tally_counts("not a dict") is None


def test_count_row_winners_ignores_unknown_labels():
    rows = [{"winner": "challenger"}, {"winner": "unknown"}, {"winner": "tie"}]
    assert _count_row_winners(rows) == {"challenger": 1, "baseline": 0, "tie": 1}


def test_malformed_rows_are_skipped_with_warning(caplog):
    art = {
        "tasks": 2,
        "tally": {"challenger": 2, "baseline": 0, "tie": 0},
        "decisive_margin": 2,
        "rows": [{"winner": "challenger"}, 42],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "rows_match_tasks" in failed_checks(result)
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_malformed_per_repo_survives(caplog):
    art = {"per_repo": [42, _artifact(tasks=1, challenger=1, baseline=0, tie=0)]}
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        result = check_tally_integrity(art)
    assert result["passed"] is True
    assert any(name.startswith("repo-0:") for name in _names(result))


def test_corrupt_string_per_repo_row_fails_closed():
    # A per_repo row serialized as a raw error string (not a result dict) is silently dropped by
    # _per_repo_list, so a partial artifact with one clean scored repo used to pass as CONSISTENT.
    # It must fail closed instead -- matching run_clean (#1357) and error_repo_share (#1362).
    art = {"per_repo": [_artifact(tasks=1, challenger=1, baseline=0, tie=0), "CLONE FAILED: fatal"]}
    result = check_tally_integrity(art)
    assert result["passed"] is False
    assert "per_repo_rows_wellformed" in failed_checks(result)


def test_corrupt_string_row_in_generalization_partition_fails_closed():
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [_artifact(tasks=1, challenger=1, baseline=0, tie=0)]},
        "held_out": {"per_repo": [_artifact(tasks=1, challenger=0, baseline=1, tie=0), "boom"]},
    }
    result = check_tally_integrity(report)
    assert result["passed"] is False
    assert "per_repo_rows_wellformed" in failed_checks(result)


def test_wellformed_per_repo_rows_pass_the_check():
    # Control: an int row and a whitespace-only string are ignored (not corrupt) -- only a
    # non-empty string is flagged -- so a clean multi-repo run stays CONSISTENT and reports the
    # well-formedness check as passing.
    art = {"per_repo": [_artifact(tasks=1, challenger=1, baseline=0, tie=0), 42, "   "]}
    result = check_tally_integrity(art)
    assert result["passed"] is True
    assert "per_repo_rows_wellformed" in _names(result)
    assert "per_repo_rows_wellformed" not in failed_checks(result)


def test_integrity_slices_expands_partition_rows():
    part = {"scored_repos": 1, "rows": _rows(1, 0, 0), "tasks": 1,
            "tally": {"challenger": 1, "baseline": 0, "tie": 0}}
    slices = _integrity_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned", part) in slices


def test_every_check_reported_when_several_fail():
    art = _artifact()
    art["tally"]["challenger"] = 99
    art["decisive_margin"] = 99
    result = check_tally_integrity(art)
    assert len(result["checks"]) == 6
    assert result["passed"] is False


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_tally_integrity(_artifact()))
    art = _artifact()
    art["tally"]["challenger"] = 99
    assert "INCONSISTENT" in integrity_headline(check_tally_integrity(art))


def test_integrity_headline_survives_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "tally integrity: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


# --- checks row sanitization for tally integrity headlines ---------------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "tally_present"}, "not a list",
    ({"name": "tally_present", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "tally_present", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "tally_present", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "tally integrity: INCONSISTENT (1/1 checks failed: tally_present)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_a_dict_row_missing_or_mistyped_name_or_passed(caplog):
    # #727: the row guard only skipped non-dict rows, so a dict row missing "name"/"passed" (or
    # carrying a wrong-typed one) slipped through and made the row["name"]/row["passed"] reads
    # raise KeyError. Such a row is now skipped with a warning, mirroring the sibling gates.
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert _check_rows_list([{"passed": False}]) == []           # missing name
        assert _check_rows_list([{"name": "tally_present"}]) == []   # missing passed
        assert _check_rows_list([{"name": 99, "passed": False}]) == []   # non-str name
        assert _check_rows_list([{"name": "x", "passed": "no"}]) == []   # non-bool passed
    good = {"name": "tally_present", "passed": False}
    assert _check_rows_list([good, {"passed": True}]) == [good]      # the valid row survives
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_a_none_name_or_none_passed(caplog):
    # `None` is the most common malformed value in a deserialized artifact and is neither a `str`
    # nor a `bool`, so both fields reject it by type and the row is skipped, never reaching the
    # row["name"]/row["passed"] reads.
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert _check_rows_list([{"name": None, "passed": False}]) == []
        assert _check_rows_list([{"name": "tally_present", "passed": None}]) == []
        assert _check_rows_list([{"name": None, "passed": None}]) == []
    assert any("name is NoneType, not str" in r.message for r in caplog.records)
    assert any("passed is NoneType, not bool" in r.message for r in caplog.records)


def test_check_rows_list_skips_a_blank_name(caplog):
    # A blank/whitespace-only name is a `str`, so the type check alone let it through and it would
    # surface as an empty entry in failed_checks / the headline's ", "-joined name list. A name
    # that carries no identity is unusable, so it is skipped like any other malformed row.
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert _check_rows_list([{"name": "", "passed": False}]) == []
        assert _check_rows_list([{"name": "   ", "passed": False}]) == []
        assert _check_rows_list([{"name": "\t\n", "passed": False}]) == []
    assert any("name is blank" in r.message for r in caplog.records)
    # and a blank-named failing row never reaches the reported output
    assert failed_checks({"checks": [{"name": "", "passed": False}]}) == []
    assert integrity_headline(
        {"passed": False, "checks": [{"name": "", "passed": False}]}
    ) == "tally integrity: no checks evaluated"


def test_failed_checks_and_headline_survive_a_check_row_missing_name():
    # #727 end to end: the reporting helpers no longer raise KeyError on a malformed row, and the
    # malformed row is excluded from both the numerator and denominator of the headline count.
    result = {"passed": False,
              "checks": [{"name": "tally_present", "passed": False}, {"passed": False}]}
    assert failed_checks(result) == ["tally_present"]
    assert failed_checks({"checks": [{"passed": False}]}) == []
    line = integrity_headline(result)
    assert line == "tally integrity: INCONSISTENT (1/1 checks failed: tally_present)"


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "tally_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.tally_integrity"):
        assert failed_checks({"checks": checks}) == ["tally_present"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_tally_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_tally_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks("not a dict") == []


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.tally_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_consistent_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_artifact()), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "CONSISTENT" in result.stderr
    assert json.loads(result.stdout)["passed"] is True


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    path = tmp_path / "bad.json"
    art = _artifact()
    art["decisive_margin"] = 99
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INCONSISTENT" in result.stderr


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    missing = tmp_path / "missing.json"
    result = _run_cli(str(missing))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "Errno" not in result.stderr
    assert f"artifact not found: {missing}" in result.stderr


def test_cli_broken_symlink_reports_clean_error(tmp_path):
    # A dangling symlink raises FileNotFoundError like a missing path; it must be named as a
    # broken link (its target is gone, the link itself exists), not reported as "not found".
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    result = _run_cli(str(link))
    assert result.returncode == 2
    assert result.stderr == f"artifact is a broken symlink (target does not exist): {link}\n"


def test_cli_directory_path_reports_clean_error(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "Errno" not in result.stderr
    assert "directory" in result.stderr


def test_cli_load_error_exit_is_distinct_from_the_strict_gate_exit(tmp_path):
    # Load errors exit 2 while a failed --strict gate exits 1, so CI can tell them apart.
    missing = tmp_path / "gone.json"
    result = _run_cli(str(missing), "--strict")
    assert result.returncode == 2
    assert result.stdout == ""


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_artifact_symlink_loop_is_named_not_leaked(monkeypatch, tmp_path, capsys):
    # A symlink loop raises OSError(ELOOP), which no specific arm catches; it must be named
    # as a loop, not leaked as a raw errno string.
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


def test_load_artifact_not_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    # A path that routes through a regular file raises NotADirectoryError; it must be named
    # distinctly instead of falling through as a raw errno string.
    path = str(tmp_path / "run.json" / "child.json")

    def _raise(*args, **kwargs):
        raise NotADirectoryError(20, "Not a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact path is not a file (a parent component is not a directory): {path}\n"
    )


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err


def test_cli_reports_a_clean_error_for_an_oversized_int_literal(tmp_path):
    # json.load raises a plain ValueError (not JSONDecodeError) for an integer literal beyond
    # the int-string-conversion limit; it must land in the same clean invalid-JSON arm.
    huge = tmp_path / "huge.json"
    huge.write_text('{"composite_mean": ' + "9" * 5000 + "}", encoding="utf-8")
    result = _run_cli(str(huge))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "not valid JSON" in result.stderr


def test_cli_reports_a_clean_error_for_a_non_utf8_artifact(tmp_path):
    # Non-UTF-8 bytes raise UnicodeDecodeError (a ValueError subclass) mid-read; it must land
    # in the clean invalid-JSON arm, not escape as a traceback.
    path = tmp_path / "latin1.json"
    path.write_bytes(b'\xff\xfe{"a": 1}')
    result = _run_cli(str(path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "not valid JSON" in result.stderr


def test_load_artifact_generic_os_error_prints_the_path_exactly_once(monkeypatch, tmp_path, capsys):
    # An OSError carrying the filename would print the path twice via str(exc); the fallback
    # uses strerror so the path appears exactly once, in the message's own prefix.
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(path)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err == f"cannot read artifact ({path}): Input/output error\n"
    assert err.count(path) == 1


def test_islink_probe_is_not_reachable_before_open_or_on_a_symlink_loop(monkeypatch, tmp_path, capsys):
    # The broken-symlink probe must run only after open() fails with FileNotFoundError: never
    # on a successful open (no pre-open TOCTOU probe) and never on the ELOOP path.
    calls = []
    real_islink = os.path.islink
    monkeypatch.setattr(os.path, "islink", lambda p: (calls.append(p), real_islink(p))[1])

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert tally_integrity_cli.load_artifact(str(good)) == {"ok": True}
    assert calls == []

    loop_path = str(tmp_path / "loop.json")

    def _eloop(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", loop_path)

    monkeypatch.setattr("builtins.open", _eloop)
    with pytest.raises(SystemExit) as excinfo:
        tally_integrity_cli.load_artifact(loop_path)
    assert excinfo.value.code == 2
    assert calls == []
    assert capsys.readouterr().err.endswith(f"artifact path is a symlink loop: {loop_path}\n")


def test_cli_reports_clean_error_for_non_object_artifact(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1, 2]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 2
    assert "must be a JSON object" in result.stderr


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "artifact is not valid JSON" in result.stderr
