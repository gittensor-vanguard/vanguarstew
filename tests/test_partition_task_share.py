"""Tests for partition task share summary and CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.partition_task_share import (  # noqa: E402
    partition_task_share_headline,
    summarize_partition_task_share,
)
from scripts import partition_task_share as cli  # noqa: E402


def _repo(tasks, name="r"):
    return {"repo": name, "tasks": tasks, "composite_mean": 0.6}


def _multi(*task_counts):
    return {
        "repos": len(task_counts),
        "scored_repos": sum(1 for t in task_counts if t > 0),
        "composite_mean": 0.6,
        "per_repo": [_repo(t, f"r{i}") for i, t in enumerate(task_counts)],
    }


def test_single_repo_counts_tasks():
    out = summarize_partition_task_share({"composite_mean": 0.6, "tasks": 8})
    assert out["kind"] == "single"
    assert out["total_tasks"] == 8
    assert out["partitions"] is None


def test_single_repo_zero_tasks():
    out = summarize_partition_task_share({"composite_mean": 0.6, "tasks": 0})
    assert out["total_tasks"] == 0


def test_multi_repo_aggregates_scored_tasks():
    out = summarize_partition_task_share(_multi(4, 0, 2))
    assert out["kind"] == "multi"
    assert out["total_tasks"] == 6
    assert out["partitions"]["multi"]["share"] == 1.0


def test_multi_empty_per_repo():
    out = summarize_partition_task_share({"per_repo": [], "composite_mean": 0.5, "repos": 0})
    assert out["total_tasks"] == 0
    assert out["partitions"] is None


def test_generalization_reports_both_partitions():
    art = {
        "tuned": _multi(6, 2),
        "held_out": _multi(4),
        "generalization_gap": 0.1,
    }
    out = summarize_partition_task_share(art)
    assert out["kind"] == "generalization"
    assert out["total_tasks"] == 12
    assert out["partitions"]["tuned"]["tasks"] == 8
    assert out["partitions"]["held_out"]["tasks"] == 4
    assert out["partitions"]["tuned"]["share"] == round(8 / 12, 3)
    assert out["partitions"]["held_out"]["share"] == round(4 / 12, 3)


def test_generalization_missing_held_out_partition():
    art = {
        "tuned": _multi(3, 3),
        "held_out": {},
        "generalization_gap": None,
    }
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 6
    assert out["partitions"]["held_out"]["tasks"] == 0
    assert out["partitions"]["held_out"]["share"] == 0.0


def test_generalization_missing_tuned_per_repo():
    art = {
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": _multi(5, 1),
        "generalization_gap": None,
    }
    out = summarize_partition_task_share(art)
    assert out["partitions"]["tuned"]["tasks"] == 0
    assert out["partitions"]["held_out"]["tasks"] == 6


def test_generalization_zero_total_yields_zero_shares():
    art = {
        "tuned": _multi(0, 0),
        "held_out": _multi(0),
        "generalization_gap": None,
    }
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 0
    assert out["partitions"]["tuned"]["share"] is None
    assert out["partitions"]["held_out"]["share"] is None


def test_malformed_row_skipped():
    art = {"per_repo": ["bad", _repo(5)], "composite_mean": 0.5, "repos": 1, "scored_repos": 1}
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 5


def test_missing_tasks_field_skipped():
    art = {"per_repo": [{"repo": "r0"}], "composite_mean": 0.5, "repos": 1, "scored_repos": 0}
    out = summarize_partition_task_share(art)
    assert out["total_tasks"] == 0


def test_negative_tasks_skipped():
    out = summarize_partition_task_share(_multi(-1, 4))
    assert out["total_tasks"] == 4


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_partition_task_share(None)
    assert out["kind"] == "invalid"
    assert out["total_tasks"] == 0


def test_unknown_shape_without_per_repo_is_single():
    out = summarize_partition_task_share({"composite_mean": 0.5})
    assert out["kind"] == "single"
    assert out["total_tasks"] == 0


def test_headline_generalization_includes_both_partitions():
    art = {
        "tuned": _multi(6),
        "held_out": _multi(2),
        "generalization_gap": 0.1,
    }
    out = summarize_partition_task_share(art)
    headline = partition_task_share_headline(out)
    assert "tuned 75.0%" in headline
    assert "held-out 25.0%" in headline


def test_headline_no_scored_tasks():
    out = summarize_partition_task_share(_multi(0, 0))
    assert partition_task_share_headline(out) == "partition task share: no scored tasks"


def test_headline_with_nan_share_does_not_crash():
    out = {
        "kind": "generalization",
        "total_tasks": 4,
        "partitions": {
            "tuned": {"tasks": 4, "share": float("nan")},
            "held_out": {"tasks": 0, "share": 0.0},
        },
    }
    headline = partition_task_share_headline(out)
    assert "n/a" in headline


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    art = {
        "tuned": _multi(6),
        "held_out": _multi(2),
        "generalization_gap": 0.1,
    }
    path = tmp_artifact("run.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["total_tasks"] == 8


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    err = capsys.readouterr().err
    assert "artifact not found" in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A real directory raises IsADirectoryError from open(); name it distinctly rather than
    # letting the generic OSError arm print "[Errno 21] Is a directory".
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and str(tmp_path) in err
    assert "Errno" not in err and "Traceback" not in err


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root bypasses file-permission bits")
def test_cli_unreadable_file_exits_two(tmp_path, capsys):
    # A real chmod-0 file raises PermissionError -> its own message naming the path.
    path = tmp_path / "locked.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        rc = cli.run([str(path)])
    finally:
        os.chmod(path, 0o644)
    assert rc == 2
    err = capsys.readouterr().err
    assert "artifact is not readable" in err and str(path) in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_broken_symlink_exits_two(tmp_path, capsys):
    # A dangling symlink would otherwise surface as FileNotFoundError ("artifact not found"),
    # blaming the path instead of the missing link target.
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "gone.json")
    assert cli.run([str(link)]) == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and str(link) in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_symlink_loop_exits_two(tmp_path, capsys):
    # A self-referential symlink never resolves (os.path.exists is False for it), so it is
    # reported as a broken link too -- still a clean, actionable message, never an ELOOP dump.
    loop = tmp_path / "loop.json"
    loop.symlink_to(loop)
    assert cli.run([str(loop)]) == 2
    err = capsys.readouterr().err
    assert "broken symlink" in err and str(loop) in err
    assert "Errno" not in err and "Traceback" not in err


def test_cli_generic_oserror_exits_two(capsys, monkeypatch):
    # The catch-all OSError arm (a device/IO error) must still exit cleanly naming the path.
    def _raise(*args, **kwargs):
        raise OSError(5, "I/O error")

    monkeypatch.setattr("builtins.open", _raise)
    assert cli.run(["flaky.json"]) == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "flaky.json" in err
    assert "Traceback" not in err


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_permission_error_exits_two(capsys):
    # PermissionError now names the permission problem distinctly instead of falling through
    # to the generic "cannot read artifact ...: [Errno 13]" arm.
    with patch("builtins.open", mock_open()) as mocked:
        mocked.side_effect = PermissionError("permission denied")
        assert cli.run(["locked.json"]) == 2
    err = capsys.readouterr().err
    assert "artifact is not readable" in err and "locked.json" in err
    assert "Errno" not in err and "Traceback" not in err
