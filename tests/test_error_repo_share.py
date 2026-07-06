"""Tests for error repo share summary and CLI (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.error_repo_share import (  # noqa: E402
    _is_number,
    _slice_summary,
    error_repo_share_headline,
    summarize_error_repo_share,
)
from scripts import error_repo_share as cli  # noqa: E402


def _repo(name, error=None, tasks=3):
    row = {"repo": name, "tasks": tasks}
    if error is not None:
        row["error"] = error
    return row


def _multi(*rows):
    return {"per_repo": list(rows), "repos": len(rows), "scored_repos": len(rows)}


def test_is_number_accepts_finite_numbers_only():
    assert _is_number(0) and _is_number(0.5)
    assert not _is_number(True)
    assert not _is_number("0.5")
    assert not _is_number(None)
    assert not _is_number(float("nan"))


def test_slice_summary_error_share():
    out = _slice_summary(_multi(_repo("a", "clone failed"), _repo("b")))
    assert out["repos_total"] == 2
    assert out["repos_error"] == 1
    assert out["error_share"] == 0.5


def test_single_repo_with_top_level_error():
    out = _slice_summary({"tasks": 0, "error": "boom"})
    assert out["repos_total"] == 1
    assert out["repos_error"] == 1
    assert out["error_share"] == 1.0


def test_empty_per_repo_yields_none_share():
    out = _slice_summary({"per_repo": []})
    assert out["repos_total"] == 0
    assert out["error_share"] is None


def test_multi_artifact_reports_share():
    summary = summarize_error_repo_share(_multi(_repo("a", "x"), _repo("b")))
    assert summary["kind"] == "multi"
    assert summary["error_share"] == 0.5
    assert summary["partitions"] is None


def test_generalization_reports_partitions_and_overall():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.05,
        "tuned": _multi(_repo("a"), _repo("b", "fail")),
        "held_out": _multi(_repo("c", "fail"), _repo("d", "fail")),
    })
    assert summary["kind"] == "generalization"
    assert summary["repos_total"] == 4
    assert summary["repos_error"] == 3
    assert summary["error_share"] == 0.75
    assert summary["partitions"]["tuned"]["error_share"] == 0.5
    assert summary["partitions"]["held_out"]["error_share"] == 1.0


def test_generalization_missing_partitions():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.0,
        "tuned": _multi(_repo("a")),
        "held_out": {},
    })
    assert summary["partitions"]["held_out"]["repos_total"] == 0
    assert summary["partitions"]["held_out"]["error_share"] is None


def test_malformed_rows_skipped():
    summary = summarize_error_repo_share({"per_repo": ["bad", _repo("a", "x")]})
    assert summary["repos_total"] == 1
    assert summary["repos_error"] == 1


def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1]):
        summary = summarize_error_repo_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["repos_total"] == 0
        assert summary["partitions"] is None


def test_headline_variants():
    summary = summarize_error_repo_share(_multi(_repo("a", "x"), _repo("b")))
    assert "50.0%" in error_repo_share_headline(summary)
    assert error_repo_share_headline({"repos_total": 0}) == "error repo share: no per-repo rows"
    assert error_repo_share_headline({}) == "error repo share: no per-repo rows"
    assert error_repo_share_headline("nope") == "error repo share: no per-repo rows"
    assert "n/a" in error_repo_share_headline({"repos_total": 2, "repos_error": 1, "error_share": None})


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps(_multi(_repo("a", "x"), _repo("b"))))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["error_share"] == 0.5


def test_cli_generalization_reports_partitions(tmp_path, capsys):
    artifact = {
        "generalization_gap": 0.05,
        "tuned": _multi(_repo("a", "x")),
        "held_out": _multi(_repo("b")),
    }
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["tuned"]["repos_error"] == 1


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_unreadable_path_is_handled(tmp_path):
    assert cli.run([str(tmp_path)]) == 2


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.error_repo_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
