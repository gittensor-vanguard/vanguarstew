"""Tests for the multi-repo aggregate integrity gate (deterministic, offline)."""

import copy
import errno
import json
import logging
import math
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.aggregate_integrity import (  # noqa: E402
    DEFAULT_TOLERANCE,
    _aggregate_slices,
    _check_rows_list,
    _is_finite_number,
    _mean_rounded,
    check_aggregate_integrity,
    failed_checks,
    integrity_headline,
)

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


def _repo(tasks=2, composite=0.6, judge=0.7, objective=0.5, name="a"):
    return {
        "repo": name,
        "tasks": tasks,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def _multi(*entries, scored_repos=None, skipped=None, repos_count=None):
    scored_list = [r for r in entries if r.get("tasks", 0) > 0]
    scored = scored_repos if scored_repos is not None else len(scored_list)
    skipped_n = skipped if skipped is not None else len(entries) - scored
    composites = [r["composite_mean"] for r in scored_list]
    judges = [r["composite_parts"]["judge_mean"] for r in scored_list]
    objectives = [r["composite_parts"]["objective_mean"] for r in scored_list]
    return {
        "repos": repos_count if repos_count is not None else len(entries),
        "scored_repos": scored,
        "skipped": skipped_n,
        "composite_mean": _mean_rounded(composites),
        "composite_parts": {
            "judge_mean": _mean_rounded(judges),
            "objective_mean": _mean_rounded(objectives),
        },
        "per_repo": list(entries),
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_multi_repo_passes():
    art = _multi(_repo(2, 0.6), _repo(3, 0.8))
    result = check_aggregate_integrity(art)
    assert result["passed"] is True
    assert "composite_mean_matches_repos" in _names(result)


def test_is_finite_number_rejects_bool_nan_inf():
    assert not _is_finite_number(True)
    assert not _is_finite_number(float("nan"))
    assert not _is_finite_number(float("inf"))
    assert _is_finite_number(0.6)


def test_is_finite_number_rejects_numpy_when_available():
    if not HAS_NUMPY:
        return
    assert not _is_finite_number(np.float64(0.6))
    assert not _is_finite_number(np.int64(3))


def test_is_finite_number_rejects_oversized_int_without_raising():
    # ``math.isfinite`` raises OverflowError for a Python int too big to convert to a float
    # (json.load yields such an int from an oversized integer literal). It must read as
    # non-finite instead of crashing the gate (#1417), matching the guard the sibling
    # integrity modules carry (weight_integrity #1365).
    assert not _is_finite_number(10**400)
    assert not _is_finite_number(-(10**400))
    assert _is_finite_number(10**15)  # large but float-convertible ints still count


def test_inflated_composite_mean_fails():
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["composite_mean"] = 0.99
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "composite_mean_matches_repos" in failed_checks(result)


def test_scored_repos_mismatch_fails():
    art = _multi(_repo(2, 0.6), _repo(0, 0.0))
    art["scored_repos"] = 2
    result = check_aggregate_integrity(art)
    assert "scored_repos_matches" in failed_checks(result)


def test_skipped_mismatch_fails():
    art = _multi(_repo(2, 0.6), _repo(0, 0.0))
    art["skipped"] = 0
    result = check_aggregate_integrity(art)
    assert "skipped_matches" in failed_checks(result)


def test_missing_scored_composite_fails_explicit_check():
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["per_repo"][0]["composite_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    assert "scored_composites_reported" in failed_checks(result)


def test_nan_headline_composite_fails():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    assert "composite_mean_matches_repos" in failed_checks(result)


def test_oversized_int_headline_composite_fails_without_raising():
    # A headline composite_mean too large to convert to a float must fail the check with a
    # clear detail, not crash check_aggregate_integrity with an OverflowError (#1417).
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 10**400
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "composite_mean_matches_repos" in failed_checks(result)


def test_oversized_int_per_repo_composite_fails_without_raising():
    # The same guard covers per-repo values: an oversized-int composite_mean on a scored repo
    # reads as missing/non-finite, failing scored_composites_reported instead of raising.
    art = _multi(_repo(2, 0.6), _repo(2, 0.8))
    art["per_repo"][0]["composite_mean"] = 10**400
    result = check_aggregate_integrity(art)
    assert "scored_composites_reported" in failed_checks(result)


def test_tolerance_accepts_small_delta():
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.601
    assert check_aggregate_integrity(art, tolerance=0.002)["passed"] is True
    assert check_aggregate_integrity(art, tolerance=0.0)["passed"] is False


def test_zero_scored_repos_headline_is_zero():
    art = _multi(_repo(0, 0.0), _repo(0, 0.0))
    assert art["composite_mean"] == 0.0
    assert check_aggregate_integrity(art)["passed"] is True


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_aggregate_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_single_repo_fails_artifact_shape():
    result = check_aggregate_integrity({"tasks": 2, "composite_mean": 0.6})
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_checks_each_partition():
    part = _multi(_repo(2, 0.6), _repo(3, 0.8))
    report = {
        "generalization_gap": 0.1,
        "tuned": part,
        "held_out": copy.deepcopy(part),
    }
    result = check_aggregate_integrity(report)
    assert result["passed"] is True
    assert "tuned:composite_mean_matches_repos" in _names(result)


def test_generalization_without_per_repo_fails():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "composite_mean": 0.6},
        "held_out": {"scored_repos": 1, "composite_mean": 0.5},
    }
    result = check_aggregate_integrity(report)
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_malformed_per_repo_skipped(caplog):
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [42, _repo(1, 0.5)], "scored_repos": 1, "skipped": 0,
                  "composite_mean": 0.5,
                  "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5}},
        "held_out": {"per_repo": [], "scored_repos": 0, "skipped": 0,
                     "composite_mean": 0.0,
                     "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}},
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(report)
    assert "tuned:composite_mean_matches_repos" in _names(result)
    assert any("per_repo[0] is int" in r.message for r in caplog.records)


def test_malformed_per_repo_entry_in_multi_repo(caplog):
    art = _multi(_repo(2, 0.6))
    art["per_repo"].insert(0, 42)
    art["repos"] = 2
    art["skipped"] = 0
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "repos_count_matches" in failed_checks(result)


def test_aggregate_slices_requires_per_repo_list():
    assert _aggregate_slices({"tuned": {}, "held_out": {}, "generalization_gap": 0}) == []
    part = _multi(_repo(1, 0.5))
    assert ("run", part) in _aggregate_slices(part)


def test_missing_composite_parts_fails():
    art = _multi(_repo(2, 0.6))
    del art["composite_parts"]
    result = check_aggregate_integrity(art)
    assert "judge_mean_matches_repos" in failed_checks(result)


def test_scored_repo_missing_component_parts_fails_explicit_check():
    """A scored repo that carries no component means must fail, not leave the denominator.

    Load-bearing: `_finite_field_values` drops such a repo and `_mean_rounded` divides by the
    survivors, so the gate used to report CONSISTENT for a headline computed from a subset —
    the exact inconsistency it exists to catch. Mirrors `scored_composites_reported`.
    """
    art = _multi(_repo(2, 0.6, judge=0.9), _repo(2, 0.5, judge=0.5, name="b"))
    del art["per_repo"][1]["composite_parts"]
    art["composite_parts"]["judge_mean"] = 0.9  # the surviving repo's value alone
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "scored_components_reported" in failed_checks(result)


def test_a_repo_cannot_count_for_composite_but_vanish_from_components():
    """The same artifact must not be checked against two different denominators."""
    art = _multi(_repo(2, 0.6, judge=0.9), _repo(2, 0.5, judge=0.5, name="b"))
    art["per_repo"][1]["composite_parts"]["judge_mean"] = float("nan")
    result = check_aggregate_integrity(art)
    # repo b still counts toward the composite denominator ...
    assert "scored_composites_reported" not in failed_checks(result)
    assert "composite_mean_matches_repos" not in failed_checks(result)
    # ... so it must count toward the component one too.
    assert "scored_components_reported" in failed_checks(result)


def test_no_per_repo_component_evidence_is_not_a_vacuous_pass():
    """`_mean_rounded([])` is 0.0, so a headline 0.0 must not verify against a fabricated 0.0."""
    art = _multi(_repo(2, 0.0, judge=0.0, objective=0.0))
    del art["per_repo"][0]["composite_parts"]
    result = check_aggregate_integrity(art)
    assert result["passed"] is False
    assert "scored_components_reported" in failed_checks(result)


def test_component_completeness_survives_degenerate_per_repo_parts():
    """Every shape a corrupt `composite_parts` can take fails the check rather than raising."""
    for parts in (None, "not a dict", 42, [], {"judge_mean": "x"}, {"judge_mean": float("inf")},
                  {"judge_mean": True}, {"objective_mean": 0.5}):
        art = _multi(_repo(2, 0.6), _repo(2, 0.5, name="b"))
        art["per_repo"][1]["composite_parts"] = parts
        result = check_aggregate_integrity(art)
        assert "scored_components_reported" in failed_checks(result), parts


def test_a_complete_multi_repo_still_passes_every_check():
    """Control: complete per-repo evidence is unaffected — the new check is caused by absence.

    Passes both before and after the fix, so it proves the failures above come from the missing
    evidence rather than from the check firing unconditionally.
    """
    art = _multi(_repo(2, 0.7, judge=0.9), _repo(2, 0.5, judge=0.5, name="b"))
    result = check_aggregate_integrity(art)
    assert result["passed"] is True, failed_checks(result)
    assert "scored_components_reported" not in failed_checks(result)


# --- #790: checks row sanitization for aggregate integrity headlines -----------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "composite_mean_matches_repos"}, "not a list",
    ({"name": "composite_mean_matches_repos", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "composite_mean_matches_repos", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "composite_mean_matches_repos", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "composite_mean_matches_repos", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "composite_mean_matches_repos", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "composite_mean_matches_repos", "passed": False},
        {"name": "scored_repos_matches", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": 99, "passed": False},
        {"name": "composite_mean_matches_repos", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert _check_rows_list([{"name": "composite_mean_matches_repos"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_integrity_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert integrity_headline({"checks": bad, "passed": False}) == (
            "aggregate integrity: no checks evaluated"
        ), bad


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_integrity_headline_survives_falsy_scalar_checks(bad):
    assert integrity_headline({"checks": bad, "passed": False}) == (
        "aggregate integrity: no checks evaluated"
    )


def test_integrity_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "composite_mean_matches_repos"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "composite_mean_matches_repos", "passed": 1}],
    ):
        assert integrity_headline({"checks": checks, "passed": False}) == (
            "aggregate integrity: no checks evaluated"
        )


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "composite_mean_matches_repos", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == (
        "aggregate integrity: INCONSISTENT (1/1 checks failed: composite_mean_matches_repos)"
    )
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "composite_mean_matches_repos"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "composite_mean_matches_repos", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "composite_mean_matches_repos", "passed": False},
        42,
        {"name": "scored_repos_matches", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.aggregate_integrity"):
        assert failed_checks({"checks": checks}) == ["composite_mean_matches_repos"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_and_failed_checks_robust():
    assert integrity_headline({}) == "aggregate integrity: no checks evaluated"
    assert failed_checks({}) == []
    bad = _multi(_repo(2, 0.6))
    bad["composite_mean"] = 0.1
    assert failed_checks(check_aggregate_integrity(bad)) == ["composite_mean_matches_repos"]


def test_check_aggregate_integrity_does_not_mutate():
    art = _multi(_repo(2, 0.6))
    before = json.dumps(art, sort_keys=True)
    check_aggregate_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_default_tolerance_is_zero():
    assert DEFAULT_TOLERANCE == 0.0
    assert math.isfinite(DEFAULT_TOLERANCE)


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.aggregate_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_strict_passes_for_consistent_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_multi(_repo(2, 0.6))), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 0
    assert "CONSISTENT" in result.stderr


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    path = tmp_path / "bad.json"
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.1
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path), "--strict")
    assert result.returncode == 1
    assert "INCONSISTENT" in result.stderr


def test_cli_without_strict_returns_zero_even_when_invalid(tmp_path):
    path = tmp_path / "bad.json"
    art = _multi(_repo(2, 0.6))
    art["composite_mean"] = 0.1
    path.write_text(json.dumps(art), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert json.loads(result.stdout)["passed"] is False


def test_cli_reports_clean_error_for_missing_file(tmp_path):
    result = _run_cli(str(tmp_path / "missing.json"))
    assert result.returncode == 2
    assert "artifact not found" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_reports_clean_error_for_non_object(tmp_path):
    path = tmp_path / "array.json"
    path.write_text(json.dumps([1]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 2
    assert "must be a JSON object" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_reports_clean_error_for_a_directory_path(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 2
    assert "artifact path is a directory, not a file" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root bypasses file permission bits")
def test_cli_reports_clean_error_for_an_unreadable_file(tmp_path):
    locked = tmp_path / "locked.json"
    locked.write_text(json.dumps(_multi()), encoding="utf-8")
    locked.chmod(0o000)
    try:
        result = _run_cli(str(locked))
    finally:
        locked.chmod(0o600)
    assert result.returncode == 2
    assert "not readable" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_reports_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr
    assert "Traceback" not in result.stderr


def test_cli_broken_symlink_reports_clean_error(tmp_path):
    # A dangling symlink raises FileNotFoundError like a missing path; it must be named as a
    # broken link (its target is gone, the link itself exists), not reported as "not found".
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    result = _run_cli(str(link))
    assert result.returncode == 2
    assert result.stderr == f"artifact is a broken symlink (target does not exist): {link}\n"


def test_cli_load_error_exit_is_distinct_from_the_strict_gate_exit(tmp_path):
    # A load error exits 2 while a failed --strict gate exits 1, so CI can tell them apart.
    result = _run_cli(str(tmp_path / "gone.json"), "--strict")
    assert result.returncode == 2
    assert result.stdout == ""


def test_load_artifact_symlink_loop_is_named_not_leaked(tmp_path, capsys, monkeypatch):
    # A symlink loop raises OSError(ELOOP), which no specific arm catches; it must be named
    # as a loop, not leaked as a raw errno string.
    from scripts import aggregate_integrity as cli

    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


def test_load_artifact_not_a_directory_error_is_named(tmp_path, capsys, monkeypatch):
    # A path routed through a regular file raises NotADirectoryError; name it distinctly
    # instead of leaking a raw errno through the generic arm.
    from scripts import aggregate_integrity as cli

    path = str(tmp_path / "run.json" / "child.json")

    def _raise(*args, **kwargs):
        raise NotADirectoryError(errno.ENOTDIR, "Not a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact path is not a file (a parent component is not a directory): {path}\n"
    )


def test_load_artifact_generic_oserror_prints_the_path_exactly_once(tmp_path, capsys, monkeypatch):
    # An OSError carrying the filename would print the path twice via str(exc); the fallback
    # uses strerror so the path appears exactly once, in the message's own prefix.
    from scripts import aggregate_integrity as cli

    path = str(tmp_path / "x.json")

    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err == f"cannot read artifact ({path}): Input/output error\n"
    assert err.count(path) == 1


def test_islink_probe_is_not_reachable_before_open_or_on_a_symlink_loop(tmp_path, capsys, monkeypatch):
    # The broken-symlink probe must run only after open() fails with FileNotFoundError: never
    # on a successful open (no pre-open TOCTOU probe) and never on the ELOOP path.
    from scripts import aggregate_integrity as cli

    calls = []
    real_islink = os.path.islink
    monkeypatch.setattr(os.path, "islink", lambda p: (calls.append(p), real_islink(p))[1])

    good = tmp_path / "good.json"
    good.write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert cli.load_artifact(str(good)) == {"ok": True}
    assert calls == []

    loop_path = str(tmp_path / "loop.json")

    def _eloop(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", loop_path)

    monkeypatch.setattr("builtins.open", _eloop)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(loop_path)
    assert excinfo.value.code == 2
    assert calls == []
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {loop_path}\n"


def test_cli_symlink_loop_on_a_real_filesystem_is_named(tmp_path):
    # End-to-end on a real self-referential symlink: opening it raises OSError(ELOOP), which the
    # loader must name as a loop (exit 2), refuting any claim the ELOOP path is untested.
    loop = tmp_path / "loop.json"
    loop.symlink_to("loop.json")  # self-loop -> ELOOP on open
    result = _run_cli(str(loop))
    assert result.returncode == 2
    assert result.stderr == f"artifact path is a symlink loop: {loop}\n"


def test_cli_not_a_directory_on_a_real_filesystem_is_reachable(tmp_path):
    # End-to-end proof the NotADirectoryError arm is REACHABLE (not dead code): a path routed
    # through a regular file raises ENOTDIR on a real open(), and the loader names it (exit 2).
    regular = tmp_path / "run.json"
    regular.write_text("{}", encoding="utf-8")
    routed = regular / "child.json"
    result = _run_cli(str(routed))
    assert result.returncode == 2
    assert result.stderr == (
        f"artifact path is not a file (a parent component is not a directory): {routed}\n"
    )
