"""Tests for the cross-artifact comparability gate and its CLI (deterministic, offline)."""

import copy
import errno
import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.comparability import (  # noqa: E402
    _check_rows_list,
    artifact_kind,
    check_comparability,
    comparability_headline,
    failed_checks,
)
from scripts import comparability as cli  # noqa: E402


def _repo(name, tasks=5, score=0.6):
    return {"repo": name, "tasks": tasks, "composite_mean": score}


def _multi(*repos):
    return {
        "repos": len(repos),
        "scored_repos": len(repos),
        "composite_mean": 0.6,
        "per_repo": [_repo(r) for r in repos],
    }


def _gen(tuned_repos, held_repos):
    return {
        "tuned": _multi(*tuned_repos),
        "held_out": _multi(*held_repos),
        "generalization_gap": 0.05,
    }


def _single(score=0.6):
    return {"composite_mean": score, "tasks": 8}


def test_artifact_kind_classification():
    assert artifact_kind(_single()) == "single"
    assert artifact_kind(_multi("a", "b")) == "multi"
    assert artifact_kind(_gen(["a"], ["b"])) == "generalization"
    assert artifact_kind([]) == "invalid"
    assert artifact_kind("oops") == "invalid"


def test_matching_multi_repo_artifacts_pass():
    result = check_comparability([_multi("r1", "r2"), _multi("r1", "r2")])
    assert result["passed"] is True
    assert result["artifact_kind"] == "multi"
    assert result["repo_sets"]["multi"] == ["r1", "r2"]
    assert failed_checks(result) == []


def test_different_multi_repo_sets_fail():
    result = check_comparability([_multi("r1", "r2"), _multi("r1", "r3")])
    assert result["passed"] is False
    assert failed_checks(result) == ["same_repo_set"]


def test_matching_generalization_partitions_pass():
    a = _gen(["t1", "t2"], ["h1"])
    b = copy.deepcopy(a)
    result = check_comparability([a, b])
    assert result["passed"] is True
    assert result["artifact_kind"] == "generalization"
    assert set(result["repo_sets"]["tuned"]) == {"t1", "t2"}
    assert result["repo_sets"]["held_out"] == ["h1"]


def test_generalization_tuned_mismatch_fails():
    result = check_comparability([_gen(["a"], ["h"]), _gen(["b"], ["h"])])
    assert result["passed"] is False
    assert "tuned_same_repo_set" in failed_checks(result)


def test_generalization_held_out_mismatch_fails():
    result = check_comparability([_gen(["a"], ["h1"]), _gen(["a"], ["h2"])])
    assert result["passed"] is False
    assert "held_out_same_repo_set" in failed_checks(result)


def test_mixed_kinds_fail_same_artifact_kind():
    result = check_comparability([_single(), _multi("a")])
    assert result["passed"] is False
    assert "same_artifact_kind" in failed_checks(result)


def test_single_repo_artifacts_pass_without_repo_signature():
    result = check_comparability([_single(0.5), _single(0.7)])
    assert result["passed"] is True
    assert result["artifact_kind"] == "single"


def test_one_artifact_fails_enough_artifacts():
    result = check_comparability([_multi("a")])
    assert result["passed"] is False
    assert failed_checks(result) == ["enough_artifacts"]


def test_non_dict_artifact_fails_enough_artifacts():
    result = check_comparability([_multi("a"), "not-a-dict"])
    assert result["passed"] is False
    assert "enough_artifacts" in failed_checks(result)


def test_empty_per_repo_fails_same_repo_set():
    art = _multi("a")
    art["per_repo"] = []
    result = check_comparability([art, _multi("a")])
    assert result["passed"] is False
    assert "same_repo_set" in failed_checks(result)


def test_malformed_per_repo_container_fails_same_repo_set():
    art = _multi("a")
    art["per_repo"] = 42
    result = check_comparability([art, _multi("a")])
    assert result["passed"] is False
    assert "same_repo_set" in failed_checks(result)


def test_non_dict_per_repo_rows_are_skipped():
    art = {"per_repo": ["oops", _repo("a")], "composite_mean": 0.5}
    result = check_comparability([art, art])
    assert result["passed"] is True
    assert result["repo_sets"]["multi"] == ["a"]


def test_comparability_headline_pass_and_fail():
    ok = check_comparability([_multi("a"), _multi("a")])
    bad = check_comparability([_multi("a"), _multi("b")])
    assert "COMPARABLE" in comparability_headline(ok)
    assert "NOT COMPARABLE" in comparability_headline(bad)


def test_failed_checks_tolerates_malformed_result():
    assert failed_checks({}) == []
    assert failed_checks({"checks": "oops"}) == []


# --- #797: checks row sanitization for comparability headlines ----------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "same_repo_set"}, "not a list",
    ({"name": "same_repo_set", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "same_repo_set", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "same_repo_set", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "same_repo_set", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "same_repo_set", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "same_repo_set", "passed": False},
        {"name": "enough_artifacts", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": 99, "passed": False},
        {"name": "same_repo_set", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_accepts_native_bool_values():
    rows = [
        {"name": "same_repo_set", "passed": True},
        {"name": "enough_artifacts", "passed": False},
    ]
    assert _check_rows_list(rows) == rows


def test_check_rows_list_rejects_int_as_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list([{"name": "same_repo_set", "passed": 1}]) == []
    assert any("passed is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_comparability_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert comparability_headline({"checks": bad, "passed": False}) == (
            "comparability: no checks evaluated"
        ), bad


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_comparability_headline_survives_falsy_scalar_checks(bad):
    assert comparability_headline({"checks": bad, "passed": False}) == (
        "comparability: no checks evaluated"
    )


def test_comparability_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "same_repo_set"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "same_repo_set", "passed": 1}],
    ):
        assert comparability_headline({"checks": checks, "passed": False}) == (
            "comparability: no checks evaluated"
        )


def test_comparability_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "same_repo_set", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        line = comparability_headline({"checks": checks, "passed": False})
    assert line == "comparability: NOT COMPARABLE (unknown, 1/1 checks failed: same_repo_set)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "same_repo_set"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "same_repo_set", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_integration_with_check_rows_list(caplog):
    checks = [
        {"name": "same_repo_set", "passed": False},
        42,
        {"name": "enough_artifacts", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.comparability"):
        assert failed_checks({"checks": checks}) == ["same_repo_set"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


@pytest.fixture
def tmp_artifacts(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_strict_exits_one_when_not_comparable(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1"))
    b = tmp_artifacts("b.json", _multi("r2"))
    assert cli.run([a, b, "--strict"]) == 1
    err = capsys.readouterr().err
    assert "NOT COMPARABLE" in err


def test_cli_without_strict_exits_zero_when_not_comparable(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1"))
    b = tmp_artifacts("b.json", _multi("r2"))
    assert cli.run([a, b]) == 0


def test_cli_strict_passes_for_comparable_artifacts(tmp_artifacts, capsys):
    a = tmp_artifacts("a.json", _multi("r1", "r2"))
    b = tmp_artifacts("b.json", _multi("r1", "r2"))
    assert cli.run([a, b, "--strict"]) == 0
    assert "COMPARABLE" in capsys.readouterr().err


def test_cli_missing_file_exits_two(tmp_artifacts, capsys):
    good = tmp_artifacts("good.json", _multi("a"))
    assert cli.run([good, "missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_rejects_non_object_json(tmp_artifacts, capsys):
    bad = tmp_artifacts("bad.json", [1, 2, 3])
    good = tmp_artifacts("good.json", _multi("a"))
    assert cli.run([good, str(bad)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_directory_path_exits_two(tmp_artifacts, tmp_path, capsys):
    # A directory artifact path is an OSError (IsADirectoryError on POSIX), not a
    # FileNotFoundError -- it must exit 2 with an actionable message, not a raw traceback.
    good = tmp_artifacts("good.json", _multi("a"))
    assert cli.run([good, str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert ("directory" in err or "not readable" in err) and "Traceback" not in err


def test_cli_broken_symlink_exits_two(tmp_artifacts, tmp_path, capsys):
    # A dangling symlink raises FileNotFoundError; islink() distinguishes it so the message
    # blames the missing target, not the (present) link path.
    good = tmp_artifacts("good.json", _multi("a"))
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "gone.json")
    assert cli.run([good, str(link)]) == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and "Traceback" not in err and "Errno" not in err


def test_cli_symlink_loop_exits_two(tmp_artifacts, tmp_path, capsys):
    # A self-referential symlink raises OSError(ELOOP), named distinctly by the catch-all.
    good = tmp_artifacts("good.json", _multi("a"))
    loop = tmp_path / "loop.json"
    loop.symlink_to(loop)
    assert cli.run([good, str(loop)]) == 2
    err = capsys.readouterr().err
    assert "symlink loop" in err and "Traceback" not in err


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    # Platform-agnostic: force IsADirectoryError (Windows raises PermissionError on a dir) so the
    # dedicated handler is proven live -- SystemExit(2), the specific message, and no traceback.
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    # A non-directory, non-permission OSError (e.g. I/O error, ENAMETOOLONG) hits the generic
    # OSError fallback rather than dumping a traceback.
    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err


def test_cli_broken_symlink_reports_clean_error(tmp_artifacts, tmp_path, capsys):
    good = tmp_artifacts("good.json", _multi("a"))
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    assert cli.run([good, str(link)]) == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


def test_load_artifact_broken_symlink_is_handled(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(link))
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


def test_load_artifact_symlink_loop_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


def test_load_artifact_generic_oserror_keeps_message(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "io.json")
    exc = OSError(5, "Input/output error", path)

    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"cannot read artifact ({path}): {exc}\n"
