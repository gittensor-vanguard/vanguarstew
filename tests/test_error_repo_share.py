"""Tests for the errored-repo share utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.error_repo_share import (  # noqa: E402
    _error_share,
    _has_error,
    _repo_error_flags,
    error_repo_share_headline,
    summarize_error_repo_share,
)
from scripts import error_repo_share as cli  # noqa: E402


def _ok(**extra):
    return {"composite_mean": 0.6, "tasks": 5, **extra}


def _err(msg="boom", **extra):
    return {"error": msg, "tasks": 0, **extra}


# --- single / multi ------------------------------------------------------------------------------

def test_single_clean_and_errored():
    assert summarize_error_repo_share(_ok())["error_share"] == 0.0
    errored = summarize_error_repo_share(_err())
    assert errored["kind"] == "single"
    assert errored == {
        "kind": "single", "repos": 1, "error_repos": 1, "error_share": 1.0, "partitions": None,
    }


def test_multi_share():
    summary = summarize_error_repo_share({"per_repo": [_ok(), _err(), _ok(), _err()]})
    assert summary["kind"] == "multi"
    assert summary["repos"] == 4
    assert summary["error_repos"] == 2
    assert summary["error_share"] == 0.5


def test_empty_per_repo_has_none_share():
    summary = summarize_error_repo_share({"per_repo": []})
    assert summary == {
        "kind": "multi", "repos": 0, "error_repos": 0, "error_share": None, "partitions": None,
    }


def test_non_countable_per_repo_entries_are_skipped():
    # Ints, None, and empty/whitespace strings carry no error signal and are not counted.
    summary = summarize_error_repo_share({"per_repo": [_err(), 5, None, "", "   ", _ok()]})
    assert summary["repos"] == 2 and summary["error_repos"] == 1


def test_malformed_string_per_repo_row_counts_as_error():
    # A per_repo row that is itself a non-empty string is a malformed/corrupt entry, not a
    # well-formed result dict — count it as an errored repo (matching the canonical
    # acceptance._partition_error and check_run_clean) so the share reflects the real failure
    # rate rather than silently under-reporting it.
    summary = summarize_error_repo_share({"per_repo": [{"tasks": 3}, "corrupt row"]})
    assert summary == {
        "kind": "multi", "repos": 2, "error_repos": 1, "error_share": 0.5, "partitions": None,
    }
    # Under a generalization partition too: the malformed row counts within its slice.
    gen = summarize_error_repo_share({
        "tuned": {"per_repo": [_ok(), "boom"]},
        "held_out": {"per_repo": [_ok()]},
        "generalization_gap": 0.0,
    })
    assert gen["partitions"]["tuned"]["error_repos"] == 1
    assert gen["partitions"]["held_out"]["error_repos"] == 0


def test_per_repo_present_does_not_double_count_top_level_error():
    # A malformed run can carry both a top-level error and a per_repo list; the per_repo rows win, so
    # the top-level error is not counted a second time.
    summary = summarize_error_repo_share({"error": "top-level boom", "per_repo": [_ok(), _ok()]})
    assert summary["error_repos"] == 0 and summary["error_share"] == 0.0


def test_empty_string_and_missing_error_are_clean():
    assert _has_error({"error": ""}) is False
    assert _has_error({"error": None}) is False
    assert _has_error({}) is False
    assert _has_error("not a dict") is False
    assert _has_error({"error": "x"}) is True


# --- generalization ------------------------------------------------------------------------------

def test_generalization_partitions_and_overall():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.05,
        "tuned": {"per_repo": [_ok(), _ok()]},
        "held_out": {"per_repo": [_err(), _ok()]},
    })
    assert summary["kind"] == "generalization"
    assert summary["repos"] == 4 and summary["error_repos"] == 1
    assert summary["error_share"] == 0.25
    assert summary["partitions"]["tuned"]["error_share"] == 0.0
    assert summary["partitions"]["held_out"]["error_share"] == 0.5


def test_generalization_missing_partitions():
    summary = summarize_error_repo_share({
        "generalization_gap": 0.0,
        "tuned": {"per_repo": []},
        "held_out": {},   # single-repo shape: one (clean) repo
    })
    assert summary["partitions"]["tuned"]["error_share"] is None
    assert summary["partitions"]["held_out"] == {"repos": 1, "error_repos": 0, "error_share": 0.0}


# --- invalid -------------------------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts():
    # {} classifies as invalid; None/scalars/lists degrade to an empty dict → also invalid.
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_error_repo_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["partitions"] is None


# --- helpers -------------------------------------------------------------------------------------

def test_error_share_helper():
    assert _error_share([]) == {"repos": 0, "error_repos": 0, "error_share": None}
    assert _error_share([True, False, False, True]) == {"repos": 4, "error_repos": 2, "error_share": 0.5}


def test_repo_error_flags_single_and_multi():
    assert _repo_error_flags({"error": "x"}) == [True]
    assert _repo_error_flags({"per_repo": [_ok(), _err()]}) == [False, True]


def test_headline_variants():
    summary = summarize_error_repo_share({"per_repo": [_ok(), _err()]})
    assert error_repo_share_headline(summary) == "error repo share: 50.0% (1/2 repos errored)"
    assert error_repo_share_headline({"repos": 0}) == "error repo share: no repos"
    assert error_repo_share_headline({}) == "error repo share: no repos"
    assert error_repo_share_headline("nope") == "error repo share: no repos"
    # Defensive: a positive repo count with a non-numeric share renders n/a, not a crash.
    assert "n/a" in error_repo_share_headline({"repos": 2, "error_repos": 0, "error_share": None})


# --- CLI: success + every error path -------------------------------------------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps({"per_repo": [_ok(), _err()]}))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["error_share"] == 0.5


def test_cli_generalization(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": {"per_repo": [_ok(), _ok()]},
                "held_out": {"per_repo": [_err(), _ok()]}}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["held_out"]["error_share"] == 0.5


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
