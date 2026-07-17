"""Tests for component mix summary and CLI (deterministic, offline)."""

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_mix import component_mix_headline, summarize_component_mix  # noqa: E402
from scripts import component_mix as cli  # noqa: E402


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def test_judge_fraction_from_parts():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert out["judge_fraction"] == 0.6
    assert out["objective_fraction"] == 0.4
    assert out["kind"] == "single"


def test_equal_parts_yield_half_fractions():
    out = summarize_component_mix(_single(0.5, 0.5))
    assert out["judge_fraction"] == 0.5
    assert out["objective_fraction"] == 0.5


def test_zero_sum_yields_none_fractions():
    out = summarize_component_mix(_single(0.0, 0.0))
    assert out["judge_fraction"] is None


def test_missing_parts_yield_none():
    out = summarize_component_mix({"composite_mean": 0.5})
    assert out["judge_fraction"] is None


def test_malformed_parts_yield_none():
    out = summarize_component_mix({"composite_parts": 42})
    assert out["judge_fraction"] is None


def test_non_numeric_parts_rejected():
    out = summarize_component_mix(_single("high", 0.4))
    assert out["judge_fraction"] is None


def test_bool_parts_rejected():
    out = summarize_component_mix(_single(True, 0.4))
    assert out["judge_fraction"] is None


def test_nan_parts_rejected():
    out = summarize_component_mix(_single(float("nan"), 0.4))
    assert out["judge_fraction"] is None


def test_overflowing_total_yields_none_fractions_not_fabricated_zero():
    # judge_mean and objective_mean are each individually finite, but their SUM overflows to
    # inf -- `total == 0` doesn't catch that, and dividing by inf used to silently produce a
    # fabricated 0.0/0.0 instead of failing closed like every other edge case here.
    out = summarize_component_mix(_single(1.5e308, 1.5e308))
    assert out["judge_mean"] == 1.5e308
    assert out["objective_mean"] == 1.5e308
    assert out["judge_fraction"] is None
    assert out["objective_fraction"] is None


def test_generalization_reports_both_partitions():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.4, 0.6),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "generalization"
    assert out["judge_fraction"] == 0.8
    assert out["partitions"]["tuned"]["judge_fraction"] == 0.8
    assert out["partitions"]["held_out"]["judge_fraction"] == 0.4


def test_generalization_missing_partition_parts():
    art = {
        "tuned": _single(0.7, 0.3),
        "held_out": {"composite_mean": 0.5},
        "generalization_gap": None,
    }
    out = summarize_component_mix(art)
    assert out["partitions"]["held_out"]["judge_fraction"] is None


def test_multi_repo_reads_top_level_parts():
    art = {
        "per_repo": [{"repo": "a", "tasks": 3}],
        "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.25},
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "multi"
    assert out["judge_fraction"] == 0.75


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_component_mix(None)
    assert out["kind"] == "invalid"


def test_headline_single():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert "judge 60.0%" in component_mix_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    headline = component_mix_headline(out)
    assert "tuned 80.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_with_nan_fraction_does_not_crash():
    out = {
        "kind": "single",
        "judge_fraction": float("nan"),
        "partitions": None,
    }
    assert "n/a" in component_mix_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _single(0.75, 0.25))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["judge_fraction"] == 0.75


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.2, 0.8),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["judge_fraction"] == 0.2


def test_cli_missing_file_exits_two(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    assert cli.run([str(missing)]) == 2
    err = capsys.readouterr().err
    assert err == f"artifact not found: {missing}\n"


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith(f"artifact is not valid JSON ({path}):")


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert capsys.readouterr().err == f"artifact must be a JSON object: {path}\n"


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # POSIX: IsADirectoryError → "directory … not a file".
    # Windows: PermissionError → "not readable" (directory permission error).
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == (
            f"artifact is not readable (check file permissions): {tmp_path}\n"
        )
    else:
        assert err == f"artifact path is a directory, not a file: {tmp_path}\n"


def test_cli_broken_symlink_exits_two(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    assert cli.run([str(link)]) == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )


@pytest.mark.skipif(
    os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0),
    reason="POSIX permission bits are not enforced on Windows; root bypasses them too",
)
def test_cli_unreadable_file_reports_clean_error(tmp_path, capsys):
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        assert cli.run([str(path)]) == 2
    finally:
        os.chmod(path, 0o644)
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_cli_symlink_to_directory_exits_two(tmp_path, capsys):
    target = tmp_path / "dir_target"
    target.mkdir()
    link = tmp_path / "link-to-dir.json"
    link.symlink_to(target)
    assert cli.run([str(link)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == (
            f"artifact is not readable (check file permissions): {link}\n"
        )
    else:
        assert err == f"artifact path is a directory, not a file: {link}\n"


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


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a directory, not a file: {path}\n"


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_load_artifact_windows_directory_permission_error_message(monkeypatch, tmp_path, capsys):
    # Explicit Windows directory-open failure path: PermissionError, exact message.
    path = str(tmp_path)

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is not readable (check file permissions): {path}\n"
    )


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")
    exc = OSError(5, "Input/output error", path)

    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"cannot read artifact ({path}): {exc}\n"
