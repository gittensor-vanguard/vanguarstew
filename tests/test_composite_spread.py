"""Tests for composite spread summary and CLI (deterministic, offline)."""

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.composite_spread import (  # noqa: E402
    composite_spread_headline,
    summarize_composite_spread,
)
from scripts import composite_spread as cli  # noqa: E402


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def test_spread_is_judge_minus_objective():
    out = summarize_composite_spread(_single(0.7, 0.5))
    assert out["spread"] == 0.2
    assert out["kind"] == "single"


def test_generalization_reads_tuned_partition():
    art = {
        "tuned": _single(0.8, 0.4),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_composite_spread(art)
    assert out["kind"] == "generalization"
    assert out["spread"] == 0.4


def test_missing_parts_yield_none_spread():
    out = summarize_composite_spread({"composite_mean": 0.5})
    assert out["spread"] is None


def test_malformed_parts_yield_none_spread():
    out = summarize_composite_spread({"composite_mean": 0.5, "composite_parts": 42})
    assert out["spread"] is None


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), float("-inf")])
def test_non_finite_mean_yields_none_spread(bad):
    # json round-trips NaN/Infinity verbatim; a non-finite mean must degrade to None/n/a rather
    # than poisoning the spread (mirrors component_mix / trend), not pass through as +inf/+nan.
    out = summarize_composite_spread(_single(bad, 0.5))
    assert out["judge_mean"] is None
    assert out["spread"] is None
    assert "n/a" in composite_spread_headline(out)


def test_oversized_int_mean_is_not_numeric():
    out = summarize_composite_spread(_single(10**400, 0.5))
    assert out["judge_mean"] is None
    assert out["spread"] is None


def test_headline():
    out = summarize_composite_spread(_single(0.6, 0.4))
    assert "delta +0.200" in composite_spread_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(payload):
        path = tmp_path / "run.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)
    return write


def test_cli(tmp_artifact, capsys):
    path = tmp_artifact(_single(0.55, 0.45))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["spread"] == 0.1


def test_cli_missing_file(tmp_path, capsys):
    # A missing path now names the real reason instead of the generic "cannot read artifact".
    assert cli.run([str(tmp_path / "missing.json")]) == 2
    assert "artifact not found" in capsys.readouterr().err


def test_cli_invalid_json(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_artifact(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "must be a JSON object" in capsys.readouterr().err


def test_cli_unreadable_path_is_handled(tmp_path, capsys):
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert ("directory, not a file" in err) or ("not readable" in err)   # POSIX / Windows


# --- path errors get a specific, actionable message -- never a raw errno string ---------------


def test_cli_directory_path_reports_the_specific_reason(tmp_path, capsys):
    # POSIX: IsADirectoryError -> "directory ... not a file".
    # Windows: PermissionError -> "not readable" (directory permission error).
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "Errno" not in err
    if os.name == "nt":
        assert err == f"artifact is not readable (check file permissions): {tmp_path}\n"
    else:
        assert err == f"artifact path is a directory, not a file: {tmp_path}\n"


def test_cli_missing_file_reports_not_found(tmp_path, capsys):
    missing = tmp_path / "nope.json"
    assert cli.run([str(missing)]) == 2
    err = capsys.readouterr().err
    assert "Errno" not in err
    assert err == f"artifact not found: {missing}\n"


def test_cli_broken_symlink_reports_the_dangling_target(tmp_path, capsys):
    # A dangling symlink raises FileNotFoundError just like a missing path; islink() separates
    # them so the message names the real problem (the link exists, its target does not).
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
def test_cli_unreadable_file_reports_a_permission_hint(tmp_path, capsys):
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


def test_load_artifact_symlink_loop_reports_a_loop(monkeypatch, tmp_path, capsys):
    # A symlink loop surfaces as a bare OSError(ELOOP), not one of the named subclasses.
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


def test_load_artifact_other_oserror_keeps_the_generic_message(monkeypatch, tmp_path, capsys):
    # A non-ELOOP OSError with no dedicated arm still reports the underlying text.
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.EIO, "Input/output error", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err.startswith(f"cannot read artifact ({path}):")
