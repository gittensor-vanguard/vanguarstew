"""Tests for the scored-fraction utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.scored_fraction import (  # noqa: E402
    _combined,
    _scored_fraction,
    _slice_fraction,
    scored_fraction_headline,
    summarize_scored_fraction,
)
from scripts import scored_fraction as cli  # noqa: E402

# --- _scored_fraction: every coherence branch ----------------------------------------------------

def test_scored_fraction_valid_and_incoherent():
    assert _scored_fraction(5, 4) == 0.8
    assert _scored_fraction(4, 4) == 1.0
    assert _scored_fraction(4, 0) == 0.0
    assert _scored_fraction(0, 0) is None       # zero repos
    assert _scored_fraction(-1, 0) is None      # negative repos
    assert _scored_fraction(3, 5) is None       # scored > repos
    assert _scored_fraction(5, -1) is None      # negative scored
    assert _scored_fraction(5.0, 4) is None     # non-integer
    assert _scored_fraction(5, True) is None    # bool


def test_fraction_ignores_skipped_field():
    # A missing/inconsistent `skipped` must never suppress a fraction repos/scored_repos can define.
    summary = summarize_scored_fraction({"repos": 5, "scored_repos": 4, "skipped": "bogus"})
    assert summary["scored_fraction"] == 0.8


# --- single / multi ------------------------------------------------------------------------------

def test_single_and_multi():
    single = summarize_scored_fraction({"repos": 4, "scored_repos": 4})
    assert single["kind"] == "single" and single["scored_fraction"] == 1.0
    multi = summarize_scored_fraction({"per_repo": [{}, {}], "repos": 10, "scored_repos": 8})
    assert multi["kind"] == "multi" and multi["scored_fraction"] == 0.8


def test_incoherent_counts_echo_raw_values():
    over = summarize_scored_fraction({"repos": 3, "scored_repos": 5})
    assert over["scored_fraction"] is None
    assert over["repos"] == 3 and over["scored_repos"] == 5
    assert summarize_scored_fraction({"repos": 5.0, "scored_repos": 4})["repos"] is None


# --- generalization (both partitions — the review's #1 gap) --------------------------------------

def test_generalization_reports_both_partitions_and_overall():
    summary = summarize_scored_fraction({
        "generalization_gap": 0.05,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 6, "scored_repos": 3},
    })
    assert summary["kind"] == "generalization"
    assert summary["repos"] == 10 and summary["scored_repos"] == 7
    assert summary["scored_fraction"] == 0.7
    assert summary["partitions"]["tuned"]["scored_fraction"] == 1.0
    assert summary["partitions"]["held_out"]["scored_fraction"] == 0.5


def test_generalization_partial_partition_withholds_overall():
    summary = summarize_scored_fraction({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {},   # missing counts
    })
    assert summary["scored_fraction"] is None
    assert summary["partitions"]["tuned"]["scored_fraction"] == 1.0
    assert summary["partitions"]["held_out"]["scored_fraction"] is None


def test_generalization_overall_is_none_when_a_partition_is_incoherent():
    # An over-scored partition (scored > repos) is malformed: its own fraction is None. The overall
    # must not sum the raw counts back into a plausible fraction (here 6/12 -> 0.5) and contradict
    # the partition — per the module's "yield None rather than a misleading value" contract.
    summary = summarize_scored_fraction({
        "generalization_gap": 0.0,
        "tuned": {"repos": 2, "scored_repos": 5},    # incoherent: 5 scored > 2 repos
        "held_out": {"repos": 10, "scored_repos": 1},
    })
    assert summary["scored_fraction"] is None
    assert summary["repos"] is None and summary["scored_repos"] is None
    assert summary["partitions"]["tuned"]["scored_fraction"] is None      # partition flagged malformed
    assert summary["partitions"]["held_out"]["scored_fraction"] == 0.1    # the coherent one still shown


def test_generalization_overall_is_none_when_a_partition_has_zero_repos():
    # A zero-repo slice is malformed too (fraction undefined), so it must null the overall rather
    # than let the other partition's fraction pass through as if it were the whole picture.
    summary = summarize_scored_fraction({
        "generalization_gap": 0.0,
        "tuned": {"repos": 0, "scored_repos": 0},    # zero-repo slice -> fraction None
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["scored_fraction"] is None
    assert summary["partitions"]["tuned"]["scored_fraction"] is None
    assert summary["partitions"]["held_out"]["scored_fraction"] == 0.5


# --- invalid / unknown kinds ---------------------------------------------------------------------

def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_scored_fraction(bad)
        assert summary["kind"] == "invalid"
        assert summary["scored_fraction"] is None
        assert summary["partitions"] is None


# --- helpers -------------------------------------------------------------------------------------

def test_slice_and_combined_helpers():
    assert _slice_fraction(None) == {"repos": None, "scored_repos": None, "scored_fraction": None}
    both = _combined(_slice_fraction({"repos": 4, "scored_repos": 4}),
                     _slice_fraction({"repos": 6, "scored_repos": 3}))
    assert both == {"repos": 10, "scored_repos": 7, "scored_fraction": 0.7}
    partial = _combined(_slice_fraction({"repos": 4, "scored_repos": 4}), _slice_fraction({}))
    assert partial == {"repos": None, "scored_repos": None, "scored_fraction": None}


def test_headline_variants():
    summary = summarize_scored_fraction({"repos": 5, "scored_repos": 4})
    assert scored_fraction_headline(summary) == "scored fraction: 80.0% (4/5 repos scored)"
    assert scored_fraction_headline({"scored_fraction": None}) == "scored fraction: n/a"
    assert scored_fraction_headline({}) == "scored fraction: n/a"
    assert scored_fraction_headline("nope") == "scored fraction: n/a"
    # Finite fraction with missing whole-number counts drops the detail clause.
    assert scored_fraction_headline({"scored_fraction": 0.8, "repos": None, "scored_repos": 4}) == (
        "scored fraction: 80.0%")


# --- CLI: success + every error path -------------------------------------------------------------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps({"repos": 5, "scored_repos": 4}))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["scored_fraction"] == 0.8


def test_cli_generalization(tmp_path, capsys):
    artifact = {"generalization_gap": 0.05, "tuned": {"repos": 4, "scored_repos": 4},
                "held_out": {"repos": 6, "scored_repos": 3}}
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    assert json.loads(capsys.readouterr().out)["partitions"]["held_out"]["scored_fraction"] == 0.5


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    assert cli.run([_write(tmp_path, "bad.json", "{not json")]) == 2


def test_cli_non_object_artifact(tmp_path):
    assert cli.run([_write(tmp_path, "arr.json", "[1, 2, 3]")]) == 2


def test_cli_non_utf8_file(tmp_path, capsys):
    # A non-UTF-8 file raises UnicodeDecodeError mid-read; keep the distinct UTF-8 message.
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"repos": 5, "scored_repos": \xff}')
    assert cli.run([str(path)]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "not valid UTF-8 JSON" in err


def test_cli_oversized_int_literal(tmp_path, capsys):
    # json.load raises a plain ValueError (not JSONDecodeError) for an oversized int literal.
    path = _write(tmp_path, "huge.json", '{"repos": ' + "9" * 5000 + "}")
    assert cli.run([path]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "not valid JSON" in err
    assert "UTF-8" not in err


def test_cli_directory_path_reports_clean_error(tmp_path, capsys):
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err
    assert "[Errno" not in err
    assert "Traceback" not in err


def test_load_artifact_permission_error_is_clean(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "artifact is not readable" in err
    assert "[Errno" not in err
    assert "Traceback" not in err


def test_module_main_no_arg_exits_nonzero():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.scored_fraction"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()
