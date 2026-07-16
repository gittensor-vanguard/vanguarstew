"""Tests for the skip-share reporting utility (deterministic, offline)."""

import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.skip_share import (  # noqa: E402
    _is_number,
    _skip_share,
    _slice_summary,
    skip_share_headline,
    summarize_skip_share,
)
from scripts import skip_share as cli  # noqa: E402

# --- _skip_share: every coherence branch (the review's edge cases) --------------------------------

def test_skip_share_valid():
    assert _skip_share(5, 4) == 0.2
    assert _skip_share(4, 4) == 0.0
    assert _skip_share(4, 0) == 1.0


def test_skip_share_incoherent_counts_return_none():
    assert _skip_share(0, 0) is None          # zero repos
    assert _skip_share(-1, 0) is None         # negative repos
    assert _skip_share(3, 5) is None          # scored > repos
    assert _skip_share(5, -1) is None         # negative scored
    assert _skip_share(5.0, 4) is None        # non-integer repos
    assert _skip_share(5, True) is None       # bool scored
    assert _skip_share(None, None) is None     # missing


# --- summarize_skip_share by artifact kind --------------------------------------------------------

def test_single_artifact():
    summary = summarize_skip_share({"repos": 5, "scored_repos": 4})
    assert summary["kind"] == "single"
    assert summary["skip_share"] == 0.2
    assert summary["skipped"] == 1
    assert summary["partitions"] is None


def test_multi_artifact():
    summary = summarize_skip_share({"per_repo": [{}, {}], "repos": 10, "scored_repos": 8})
    assert summary["kind"] == "multi"
    assert summary["skip_share"] == 0.2
    assert summary["partitions"] is None


def test_generalization_reports_each_partition():
    summary = summarize_skip_share({
        "generalization_gap": 0.05,
        "repos": 8,
        "scored_repos": 6,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["kind"] == "generalization"
    assert summary["skip_share"] == 0.25
    assert summary["partitions"]["tuned"]["skip_share"] == 0.0
    assert summary["partitions"]["held_out"]["skip_share"] == 0.5


def test_generalization_overall_sums_partitions_when_no_top_level_counts():
    # A --generalization artifact from run_generalization_report carries repos/scored_repos only
    # under tuned/held_out — no top-level block. The overall skip share must sum the partitions
    # (mirroring scored_fraction / order_agree_rate).
    summary = summarize_skip_share({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["repos"] == 8
    assert summary["scored_repos"] == 6
    assert summary["skipped"] == 2
    assert summary["skip_share"] == 0.25
    assert summary["partitions"]["tuned"]["skip_share"] == 0.0
    assert summary["partitions"]["held_out"]["skip_share"] == 0.5


def test_generalization_overall_is_none_when_a_partition_is_incoherent():
    # An over-scored partition (scored > repos) is malformed: its own skip_share is None. The
    # overall must not sum the raw counts back into a plausible share (here 8 scored of 8 -> 0.0)
    # and contradict the partition — per the module's "malformed accounting yields None" contract.
    summary = summarize_skip_share({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4, "scored_repos": 6},   # incoherent: 6 scored > 4 repos
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["skip_share"] is None
    assert summary["skipped"] is None
    assert summary["repos"] is None and summary["scored_repos"] is None
    assert summary["partitions"]["tuned"]["skip_share"] is None       # partition flagged malformed
    assert summary["partitions"]["held_out"]["skip_share"] == 0.5     # the coherent one still shown


def test_generalization_overall_is_none_when_a_partition_has_zero_repos():
    # A zero-repo slice is malformed too (skip_share undefined), so it must null the overall rather
    # than let the other partition's share pass through as if it were the whole picture.
    summary = summarize_skip_share({
        "generalization_gap": 0.0,
        "tuned": {"repos": 0, "scored_repos": 0},   # zero-repo slice -> skip_share None
        "held_out": {"repos": 4, "scored_repos": 2},
    })
    assert summary["skip_share"] is None
    assert summary["partitions"]["tuned"]["skip_share"] is None
    assert summary["partitions"]["held_out"]["skip_share"] == 0.5


def test_generalization_missing_partition_keys():
    summary = summarize_skip_share({
        "generalization_gap": 0.0,
        "tuned": {"repos": 4},        # missing scored_repos
        "held_out": {},               # missing both
    })
    assert summary["skip_share"] is None
    assert summary["partitions"]["tuned"]["skip_share"] is None
    assert summary["partitions"]["tuned"]["repos"] == 4
    assert summary["partitions"]["tuned"]["scored_repos"] is None
    assert summary["partitions"]["held_out"] == {
        "repos": None, "scored_repos": None, "skipped": None, "skip_share": None,
    }


def test_zero_negative_and_over_scored_counts():
    assert summarize_skip_share({"repos": 0, "scored_repos": 0})["skip_share"] is None
    assert summarize_skip_share({"repos": -3, "scored_repos": 0})["skip_share"] is None
    over = summarize_skip_share({"repos": 3, "scored_repos": 5})
    assert over["skip_share"] is None and over["skipped"] is None
    assert over["repos"] == 3 and over["scored_repos"] == 5  # raw counts still echoed


def test_invalid_and_non_dict_artifacts():
    for bad in ({}, None, 5, "x", [1, 2]):
        summary = summarize_skip_share(bad)
        assert summary["kind"] == "invalid"
        assert summary["skip_share"] is None
        assert summary["partitions"] is None


def test_non_integer_counts_are_malformed():
    summary = summarize_skip_share({"repos": 5.0, "scored_repos": 4})
    assert summary["skip_share"] is None
    assert summary["repos"] is None  # 5.0 is not a whole-number count


def test_slice_summary_on_non_dict():
    assert _slice_summary(None) == {
        "repos": None, "scored_repos": None, "skipped": None, "skip_share": None,
    }


# --- headline: finite formatting + graceful non-finite (the review's crash) ------------------------

def test_headline_reports_percentage_and_counts():
    summary = summarize_skip_share({"repos": 5, "scored_repos": 4})
    assert skip_share_headline(summary) == "skip share: 20.0% (1 of 5 repos skipped)"


def test_headline_degrades_on_non_finite_or_missing_share():
    assert skip_share_headline({"skip_share": float("nan"), "skipped": 1, "repos": 5}).startswith(
        "skip share: n/a")
    assert skip_share_headline({"skip_share": float("inf")}) == "skip share: n/a"
    assert skip_share_headline({"skip_share": None}) == "skip share: n/a"
    assert skip_share_headline({}) == "skip share: n/a"
    assert skip_share_headline("not a dict") == "skip share: n/a"


def test_headline_finite_share_but_missing_counts_omits_detail():
    # A finite share with no whole-number skipped/repos drops the "(x of y)" clause instead of
    # formatting None counts.
    assert skip_share_headline({"skip_share": 0.2, "skipped": None, "repos": 5}) == "skip share: 20.0%"
    assert skip_share_headline({"skip_share": 0.2, "skipped": 1, "repos": None}) == "skip share: 20.0%"


def test_is_number_guard():
    assert _is_number(0.5) and _is_number(3)
    assert not _is_number(float("nan"))
    assert not _is_number(float("inf"))
    assert not _is_number(True)
    assert not _is_number("0.5")


def test_is_number_guards_an_oversized_int_overflow():
    # math.isfinite() raises OverflowError for a Python int too large to convert to a float
    # (a hand-edited or degenerate skip_share field) -- must degrade to non-numeric, not crash.
    # Covers both signs: OverflowError fires the same way for a huge positive or negative int.
    assert not _is_number(10**400)
    assert not _is_number(-(10**400))
    assert not _is_number(-(10**309))


def test_is_number_bool_rejection_is_unchanged_by_the_overflow_guard():
    # The overflow guard must not alter the pre-existing bool-rejection behavior: a bool is
    # non-numeric regardless of its truthiness, exactly as before this fix.
    assert _is_number(True) is False
    assert _is_number(False) is False


def test_is_number_at_the_float_conversion_boundary():
    # Just inside float's representable range still converts and is finite; just past it raises
    # OverflowError, which the guard must catch (the exact boundary this fix targets).
    just_under_max = int(sys.float_info.max) - 1
    just_over_max = 10**309
    assert _is_number(just_under_max) is True
    assert _is_number(just_over_max) is False


def test_headline_degrades_on_an_oversized_int_share_instead_of_crashing():
    assert skip_share_headline({"skip_share": 10**400}) == "skip share: n/a"
    assert skip_share_headline({"skip_share": -(10**400)}) == "skip share: n/a"


# --- CLI: success + every error path (the review: "CLI error handling entirely untested") ---------

def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_cli_success(tmp_path, capsys):
    path = _write(tmp_path, "ok.json", json.dumps({"repos": 5, "scored_repos": 4}))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["skip_share"] == 0.2


def test_cli_reports_generalization_partitions(tmp_path, capsys):
    # The CLI must surface the per-partition breakdown for a --generalization artifact, not just the
    # top-level share.
    artifact = {
        "generalization_gap": 0.05,
        "repos": 8,
        "scored_repos": 6,
        "tuned": {"repos": 4, "scored_repos": 4},
        "held_out": {"repos": 4, "scored_repos": 2},
    }
    path = _write(tmp_path, "gen.json", json.dumps(artifact))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["kind"] == "generalization"
    assert body["skip_share"] == 0.25
    assert body["partitions"]["tuned"]["skip_share"] == 0.0
    assert body["partitions"]["held_out"]["skip_share"] == 0.5


def test_cli_missing_file(tmp_path):
    assert cli.run([str(tmp_path / "nope.json")]) == 2


def test_cli_invalid_json(tmp_path):
    path = _write(tmp_path, "bad.json", "{not valid json")
    assert cli.run([path]) == 2


def test_cli_non_object_artifact(tmp_path):
    path = _write(tmp_path, "arr.json", "[1, 2, 3]")
    assert cli.run([path]) == 2


def test_module_main_is_runnable():
    # `python -m scripts.skip_share` with no artifact arg exits non-zero via argparse (exercises main()).
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.skip_share"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 0
    assert "artifact" in proc.stderr.lower()


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory artifact path is an OSError (IsADirectoryError on POSIX), not a
    # FileNotFoundError -- it must exit 2 with an actionable message, not a raw traceback.
    assert cli.run([str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert ("directory" in err or "not readable" in err) and "Traceback" not in err


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
    # A non-directory, non-permission OSError (e.g. I/O error) hits the generic OSError fallback
    # rather than dumping a traceback.
    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err
