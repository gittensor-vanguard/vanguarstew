"""Tests for order agree rate summary and CLI (deterministic, offline)."""

import errno
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.order_agree_rate import (  # noqa: E402
    order_agree_rate_headline,
    summarize_order_agree_rate,
)
from scripts import order_agree_rate as cli  # noqa: E402


def _stats(agree=3, disagree=1, tie=1):
    return {
        "composite_mean": 0.6,
        "judge_order_stats": {
            "agree": agree,
            "disagree": disagree,
            "tie": tie,
            "dual_order_tasks": agree + disagree + tie,
        },
    }


def test_agree_rate_from_complete_stats():
    out = summarize_order_agree_rate(_stats(6, 2, 2))
    assert out["total"] == 10
    assert out["agree_rate"] == 0.6


def test_zero_total_yields_none_rate():
    out = summarize_order_agree_rate(_stats(0, 0, 0))
    assert out["total"] == 0
    assert out["agree_rate"] is None


def test_missing_stats_yields_none():
    out = summarize_order_agree_rate({"composite_mean": 0.5})
    assert out["agree_rate"] is None


def test_malformed_stats_yields_none():
    art = {"judge_order_stats": {"agree": 1, "disagree": "x", "tie": 0}}
    out = summarize_order_agree_rate(art)
    assert out["agree_rate"] is None


def test_negative_counts_rejected():
    out = summarize_order_agree_rate(_stats(-1, 1, 0))
    assert out["agree_rate"] is None


def test_float_counts_rejected():
    art = {"judge_order_stats": {"agree": 1.5, "disagree": 0, "tie": 0}}
    out = summarize_order_agree_rate(art)
    assert out["agree_rate"] is None


def test_non_dict_stats_logged_and_treated_as_empty():
    out = summarize_order_agree_rate({"judge_order_stats": 42})
    assert out["agree_rate"] is None


def test_generalization_reports_both_partitions():
    art = {
        "generalization_gap": 0.1,
        "judge_order_stats": {"agree": 2, "disagree": 0, "tie": 0},
        "tuned": _stats(4, 0, 0),
        "held_out": _stats(1, 3, 0),
    }
    out = summarize_order_agree_rate(art)
    assert out["kind"] == "generalization"
    assert out["agree_rate"] == 0.625  # overall sums partitions (5/8), not top-level stats
    assert out["partitions"]["tuned"]["agree_rate"] == 1.0
    assert out["partitions"]["held_out"]["agree_rate"] == 0.25


def test_generalization_overall_sums_partitions_when_no_top_level_stats():
    # A --generalization artifact from run_generalization_report carries judge_order_stats only
    # under tuned/held_out — no top-level block. The overall agree rate must sum the partitions
    # (mirroring offline_share / dual_order_share).
    art = {
        "generalization_gap": 0.0,
        "tuned": _stats(3, 1, 0),
        "held_out": _stats(1, 2, 1),
    }
    out = summarize_order_agree_rate(art)
    assert out["agree"] == 4
    assert out["disagree"] == 3
    assert out["tie"] == 1
    assert out["total"] == 8
    assert out["agree_rate"] == 0.5
    assert out["partitions"]["tuned"]["agree_rate"] == 0.75
    assert out["partitions"]["held_out"]["agree_rate"] == 0.25


def test_generalization_missing_partition_stats():
    art = {
        "tuned": _stats(2, 0, 0),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_order_agree_rate(art)
    assert out["partitions"]["held_out"]["agree_rate"] is None


def test_generalization_overall_null_when_a_partition_has_zero_tasks():
    # A zero-task slice has integer (all-zero) counts but no defined agree_rate; it must not be
    # summed into a plausible-but-wrong overall from the other partition alone -- the overall is
    # None, mirroring scored_fraction (#1274), skip_share (#1272), and dual_order_coverage
    # (#1280). The coherent partition's own rate is still reported under `partitions`.
    art = {
        "generalization_gap": 0.0,
        "tuned": _stats(0, 0, 0),          # zero dual-order tasks
        "held_out": _stats(7, 3, 0),
    }
    out = summarize_order_agree_rate(art)
    assert out["partitions"]["tuned"]["total"] == 0
    assert out["partitions"]["tuned"]["agree_rate"] is None
    assert out["partitions"]["held_out"]["agree_rate"] == 0.7
    assert out["total"] is None
    assert out["agree"] is None
    assert out["agree_rate"] is None


def test_multi_repo_uses_top_level_stats():
    art = {
        "per_repo": [{"repo": "a", "tasks": 3}],
        "judge_order_stats": {"agree": 3, "disagree": 0, "tie": 0},
    }
    out = summarize_order_agree_rate(art)
    assert out["kind"] == "multi"
    assert out["agree_rate"] == 1.0


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_order_agree_rate(None)
    assert out["kind"] == "invalid"


def test_headline_happy_path():
    out = summarize_order_agree_rate(_stats(3, 1, 1))
    assert "60.0%" in order_agree_rate_headline(out)
    assert "3/5" in order_agree_rate_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "judge_order_stats": {"agree": 2, "disagree": 0, "tie": 0},
        "tuned": _stats(4, 0, 0),
        "held_out": _stats(1, 1, 0),
        "generalization_gap": 0.1,
    }
    out = summarize_order_agree_rate(art)
    headline = order_agree_rate_headline(out)
    assert "tuned 100.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_zero_total():
    out = summarize_order_agree_rate(_stats(0, 0, 0))
    assert order_agree_rate_headline(out) == "order agree rate: no dual-order stats available"


def test_headline_with_nan_rate_does_not_crash():
    out = {
        "kind": "single",
        "agree": 1,
        "total": 2,
        "agree_rate": float("nan"),
        "partitions": None,
    }
    assert "n/a" in order_agree_rate_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _stats(2, 1, 0))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["agree_rate"] == round(2 / 3, 3)


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "judge_order_stats": {"agree": 1, "disagree": 0, "tie": 0},
        "tuned": _stats(2, 0, 0),
        "held_out": _stats(0, 2, 0),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["agree_rate"] == 0.0


def test_cli_missing_file_exits_two(tmp_path, capsys):
    missing = tmp_path / "missing.json"
    assert cli.run([str(missing)]) == 2
    assert capsys.readouterr().err == f"artifact not found: {missing}\n"


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


def test_cli_oversized_int_literal_exits_two(tmp_path, capsys):
    path = tmp_path / "huge.json"
    path.write_text('{"agree": ' + "9" * 5000 + "}", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert err.startswith(f"artifact is not valid JSON ({path}):")


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "locked.json")

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


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "run.json")

    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a directory, not a file: {path}\n"


def test_load_artifact_symlink_loop_is_handled(monkeypatch, tmp_path, capsys):
    path = str(tmp_path / "loop.json")

    def _raise(*args, **kwargs):
        raise OSError(errno.ELOOP, "Too many levels of symbolic links", path)

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(path)
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == f"artifact path is a symlink loop: {path}\n"


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


def test_load_artifact_broken_symlink_is_handled(tmp_path, capsys):
    link = tmp_path / "broken.json"
    link.symlink_to(tmp_path / "nonexistent.json")
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(link))
    assert excinfo.value.code == 2
    assert capsys.readouterr().err == (
        f"artifact is a broken symlink (target does not exist): {link}\n"
    )
