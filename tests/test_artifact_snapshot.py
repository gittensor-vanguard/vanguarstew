"""Tests for replay artifact snapshot extraction and its CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.artifact_snapshot import snapshot, snapshot_headline  # noqa: E402
from scripts import artifact_snapshot as cli  # noqa: E402


def _repo(name, tasks=5, score=0.6, error=None):
    row = {"repo": name, "tasks": tasks, "composite_mean": score}
    if error:
        row["error"] = error
    return row


def _multi(*repos, scored=None):
    scored = scored if scored is not None else len(repos)
    return {
        "repos": len(repos),
        "scored_repos": scored,
        "skipped": len(repos) - scored,
        "composite_mean": 0.65,
        "decisive_margin": 2,
        "offline": True,
        "per_repo": [_repo(r) for r in repos],
    }


def _gen():
    return {
        "repo_set": "example.json",
        "tuned": _multi("t1", "t2"),
        "held_out": _multi("h1"),
        "generalization_gap": 0.08,
    }


def _single(score=0.7, tasks=8):
    return {
        "composite_mean": score,
        "tasks": tasks,
        "decisive_margin": 1,
        "offline": False,
    }


def test_single_repo_snapshot():
    out = snapshot(_single())
    assert out["kind"] == "single"
    assert out["headline_score"] == 0.7
    assert out["scored"] is True
    assert out["tasks"] == 8
    assert out["repos"] is None
    assert out["has_error"] is False
    assert out["offline"] is False


def test_multi_repo_snapshot():
    out = snapshot(_multi("a", "b", "c"))
    assert out["kind"] == "multi"
    assert out["headline_score"] == 0.65
    assert out["tasks"] == 15
    assert out["repos"] == {"total": 3, "scored": 3, "skipped": 0}
    assert out["decisive_margin"] == 2
    assert out["offline"] is True


def test_generalization_snapshot_uses_tuned_headline_and_sums_tasks():
    out = snapshot(_gen())
    assert out["kind"] == "generalization"
    assert out["headline_score"] == 0.65
    assert out["tasks"] == 15
    assert out["generalization_gap"] == 0.08
    assert out["repo_set"] == "example.json"
    assert out["repos"] == {"total": 2, "scored": 2, "skipped": 0}


def test_zero_scored_repos_marks_unscored():
    art = _multi("a", scored=0)
    art["composite_mean"] = 0.0
    out = snapshot(art)
    assert out["headline_score"] is None
    assert out["scored"] is False


def test_top_level_error_sets_has_error():
    out = snapshot({"error": "clone failed", "tasks": 0})
    assert out["has_error"] is True
    assert out["headline_score"] is None


def test_per_repo_error_sets_has_error():
    art = _multi("ok")
    art["per_repo"].append(_repo("bad", error="freeze failed"))
    out = snapshot(art)
    assert out["has_error"] is True


def test_partition_error_in_generalization():
    art = _gen()
    art["held_out"]["error"] = "repo set empty"
    out = snapshot(art)
    assert out["has_error"] is True


def test_malformed_per_repo_still_counts_valid_rows():
    art = {"per_repo": ["oops", _repo("a", tasks=4)], "composite_mean": 0.5, "repos": 1,
           "scored_repos": 1, "skipped": 0}
    out = snapshot(art)
    assert out["tasks"] == 4
    assert out["has_error"] is True


def test_bare_string_per_repo_row_sets_has_error():
    art = _multi("ok")
    art["per_repo"].append("corrupt row")
    out = snapshot(art)
    assert out["has_error"] is True
    assert "status=error" in snapshot_headline(out)


def test_blank_string_per_repo_row_does_not_set_has_error():
    art = _multi("ok")
    art["per_repo"].append("   ")
    out = snapshot(art)
    assert out["has_error"] is False


def test_generalization_partition_bare_string_per_repo_sets_has_error():
    art = _gen()
    art["tuned"]["per_repo"].append("corrupt")
    out = snapshot(art)
    assert out["has_error"] is True


def test_has_error_tolerates_missing_per_repo_and_non_list_per_repo():
    assert snapshot(_multi("a"))["has_error"] is False
    art = {"per_repo": "oops", "composite_mean": 0.5, "repos": 1, "scored_repos": 1, "skipped": 0}
    out = snapshot(art)
    assert out["has_error"] is False


def test_has_error_per_repo_none_does_not_crash():
    art = {"composite_mean": 0.5, "repos": 1, "scored_repos": 1, "skipped": 0, "per_repo": None}
    assert snapshot(art)["has_error"] is False


def test_has_error_per_repo_with_none_and_non_dict_entries_does_not_crash():
    art = {"per_repo": [_repo("a"), None, 42], "composite_mean": 0.5, "repos": 1,
           "scored_repos": 1, "skipped": 0}
    assert snapshot(art)["has_error"] is False


def test_falsy_per_repo_error_values_do_not_set_has_error():
    for falsy in (0, False, None, ""):
        art = _multi("ok")
        art["per_repo"].append({"repo": "x", "tasks": 0, "error": falsy})
        assert snapshot(art)["has_error"] is False, falsy


def test_non_finite_top_level_tasks_snapshots_none_instead_of_raising():
    # Previously ValueError/OverflowError from int(float("nan"))/int(float("inf")) in _task_total.
    # A NaN/Infinity count survives a JSON round trip but is not usable -- report None, don't crash.
    for bad in (float("nan"), float("inf")):
        out = snapshot({"composite_mean": 0.5, "tasks": bad})   # must not raise
        assert out["tasks"] is None, bad


def test_non_finite_per_repo_tasks_are_skipped_not_crashing():
    # A non-finite per_repo tasks row is skipped like any malformed row; a coherent row still counts.
    art = {"per_repo": [{"repo": "a", "tasks": float("inf")}, _repo("b", tasks=4)],
           "composite_mean": 0.5, "repos": 1, "scored_repos": 1, "skipped": 0}
    out = snapshot(art)          # must not raise
    assert out["tasks"] == 4


def test_non_finite_tasks_never_raise_for_any_variant():
    # NaN, +/-Infinity, and an int too large for a float all survive a JSON round trip and would
    # crash int(); none may raise, at the top level or inside a per_repo/generalization slice.
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        assert isinstance(snapshot({"composite_mean": 0.5, "tasks": bad}), dict), bad
        assert isinstance(snapshot({"per_repo": [{"repo": "a", "tasks": bad}]}), dict), bad
        gen = {"tuned": {"per_repo": [{"repo": "t", "tasks": bad}]},
               "held_out": {"per_repo": [{"repo": "h", "tasks": 3}]},
               "generalization_gap": 0.1}
        assert isinstance(snapshot(gen), dict), bad


def test_non_finite_generalization_gap_snapshots_none():
    # A non-finite generalization_gap must not be emitted into the snapshot (NaN/Infinity are not
    # valid JSON and not usable numbers); it degrades to None like any other unavailable value.
    for bad in (float("nan"), float("inf"), float("-inf")):
        art = {"tuned": {"composite_mean": 0.6, "scored_repos": 2, "per_repo": [{"tasks": 3}]},
               "held_out": {"composite_mean": 0.5, "scored_repos": 1, "per_repo": [{"tasks": 2}]},
               "generalization_gap": bad}
        assert snapshot(art)["generalization_gap"] is None, bad


def test_non_finite_decisive_margin_snapshots_none():
    # decisive_margin is likewise withheld when non-finite rather than propagated into the snapshot.
    for bad in (float("nan"), float("inf"), float("-inf")):
        out = snapshot({"composite_mean": 0.6, "tasks": 3, "decisive_margin": bad})
        assert out["decisive_margin"] is None, bad


def test_multi_repo_decisive_margin_from_judge_report():
    # A multi-repo aggregate carries no top-level decisive_margin; the win/loss counts live in
    # judge_report, so derive wins - losses (mirrors margin_outlook / promotion). Previously the
    # snapshot published decisive_margin=null for every multi-repo run.
    out = snapshot({"per_repo": [{"repo": "a", "tasks": 5}],
                    "judge_report": {"wins": 7, "losses": 2, "ties": 1}, "composite_mean": 0.6})
    assert out["kind"] == "multi"
    assert out["decisive_margin"] == 5


def test_generalization_decisive_margin_from_tuned_judge_report():
    # A generalization run derives the margin from the tuned (headline) partition's judge_report.
    out = snapshot({
        "generalization_gap": 0.1,
        "tuned": {"per_repo": [{"repo": "a", "tasks": 4}], "judge_report": {"wins": 6, "losses": 1}},
        "held_out": {"per_repo": [{"repo": "b", "tasks": 3}], "judge_report": {"wins": 9, "losses": 0}},
    })
    assert out["kind"] == "generalization"
    assert out["decisive_margin"] == 5     # tuned 6-1, not held_out


def test_top_level_decisive_margin_takes_precedence_over_judge_report():
    out = snapshot({"tasks": 5, "decisive_margin": 3, "judge_report": {"wins": 9, "losses": 0}})
    assert out["decisive_margin"] == 3


def test_malformed_judge_report_decisive_margin_is_none():
    # A judge_report missing losses (or with a non-int count) can't derive a margin -> None.
    out = snapshot({"per_repo": [{"repo": "a", "tasks": 5}], "judge_report": {"wins": 7}})
    assert out["decisive_margin"] is None


def test_non_finite_composite_is_unscored_without_raising():
    # A non-finite headline composite is treated as unscored (via the hardened trend reader); the
    # snapshot and its headline never raise.
    out = snapshot({"composite_mean": float("inf"), "tasks": 3})
    assert out["scored"] is False and out["headline_score"] is None
    snapshot_headline(out)   # must not raise


def test_invalid_artifact_kind():
    out = snapshot("not-a-dict")
    assert out["kind"] == "invalid"
    assert out["scored"] is False


def test_snapshot_headline():
    ok = snapshot(_single())
    bad = snapshot({"error": "x"})
    assert "headline=0.700" in snapshot_headline(ok)
    assert "status=error" in snapshot_headline(bad)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_prints_snapshot_json(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _single())
    assert cli.run([path]) == 0
    out = capsys.readouterr()
    body = json.loads(out.out)
    assert body["kind"] == "single"
    assert "snapshot:" in out.err


def test_cli_multiple_artifacts_wraps_paths(tmp_artifact, capsys):
    a = tmp_artifact("a.json", _single(0.5))
    b = tmp_artifact("b.json", _single(0.6))
    assert cli.run([a, b]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 2
    assert rows[0]["path"].endswith("a.json")


def test_cli_missing_file_exits_two(tmp_artifact, capsys):
    good = tmp_artifact("good.json", _single())
    assert cli.run([good, "missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_directory_path_exits_two(tmp_path, capsys):
    # A directory path raises IsADirectoryError inside open(); the CLI must report it cleanly and
    # exit 2, not dump a raw traceback (mirrors generalization_gate #1446 / objective_integrity #1377).
    assert cli.run([str(tmp_path)]) == 2
    assert "directory" in capsys.readouterr().err


def test_cli_unreadable_file_exits_two(capsys):
    # An unreadable file raises PermissionError; the CLI reports it cleanly and exits 2.
    with patch("builtins.open", side_effect=PermissionError("denied")):
        assert cli.run(["locked.json"]) == 2
    assert "not readable" in capsys.readouterr().err


def test_cli_generic_os_error_exits_two(capsys):
    # Any other OSError (e.g. an I/O error) is reported cleanly with its message, not a traceback.
    with patch("builtins.open", side_effect=OSError("I/O error")):
        assert cli.run(["flaky.json"]) == 2
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "I/O error" in err
