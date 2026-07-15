"""Tests for replay artifact Markdown reporting."""

import copy
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import (  # noqa: E402
    _composite_parts_dict,
    _fmt_rate,
    _fmt_score,
    _is_multi_repo,
    _per_repo_rows,
    render_report,
)
from scripts.report import load_artifact  # noqa: E402


def _single_repo():
    return {
        "tasks": 3,
        "baseline": "empty",
        "composite_mean": 0.65,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.55},
        "weights": {"judge": 0.6, "objective": 0.4},
        "judge_report": {
            "wins": 2,
            "losses": 1,
            "ties": 0,
            "disagreement_rate": 0.25,
        },
    }


def _multi_repo():
    return {
        "repos": 2,
        "scored_repos": 2,
        "skipped": 0,
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": 0.65, "objective_mean": 0.5},
        "judge_report": {
            "wins": 3,
            "losses": 2,
            "ties": 1,
            "disagreement_rate": 0.2,
        },
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.55, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.65, "tasks": 3},
        ],
    }


def _generalization():
    return {
        "repo_set": "benchmark/repo_sets/curated.json",
        "generalization_gap": 0.05,
        "tuned": {
            "scored_repos": 1,
            "composite_mean": 0.7,
            "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.55},
            "judge_report": {"wins": 2, "losses": 0, "ties": 0, "disagreement_rate": 0.0},
            "per_repo": [{"repo_name": "tuned-a", "composite_mean": 0.7, "tasks": 2}],
        },
        "held_out": {
            "scored_repos": 1,
            "composite_mean": 0.65,
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
            "judge_report": {"wins": 1, "losses": 1, "ties": 0, "disagreement_rate": 0.5},
            "per_repo": [{"repo_name": "held-b", "composite_mean": 0.65, "tasks": 2}],
        },
    }


def test_render_single_repo_includes_headline_and_judge():
    md = render_report(_single_repo())
    assert "# Benchmark report (single-repo)" in md
    assert "Composite mean: 0.650" in md
    assert "Judge mean: 0.700" in md
    assert "Objective mean: 0.550" in md
    assert "Judge W-L-T: 2-1-0" in md
    assert "Order disagreement rate: 25.0%" in md
    assert "Tasks: 3" in md


def test_render_multi_repo_includes_per_repo_table():
    md = render_report(_multi_repo())
    assert "# Benchmark report (multi-repo)" in md
    assert "### Per-repo" in md
    assert "| /a | 0.550 | 2 |" in md
    assert "| /b | 0.650 | 3 |" in md
    assert "Repos: 2/2 scored" in md


def test_render_generalization_includes_gap_and_partitions():
    md = render_report(_generalization())
    assert "# Benchmark report (generalization)" in md
    assert "Generalization gap (tuned − held-out): 0.050" in md
    assert "Verdict: pass" in md
    assert "### Tuned" in md
    assert "### Held-out" in md
    assert "| tuned-a | 0.700 | 2 |" in md
    assert "| held-b | 0.650 | 2 |" in md


def test_render_treats_unscored_partition_composite_as_unavailable():
    # A tuned partition that scored 0 repos (empty/unusable repo set for that run) carries a
    # placeholder composite_mean: 0.0 from run_multi_replay's own _mean([]) fallback -- that must
    # render as n/a, not a fabricated perfect zero, while a genuinely-scored partition alongside
    # it (held-out) still shows its real score.
    art = _generalization()
    art["tuned"] = {
        "repos": 2,
        "scored_repos": 0,
        "skipped": 2,
        "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        "per_repo": [
            {"repo_name": "tuned-a", "error": "no usable tasks", "tasks": 0},
            {"repo_name": "tuned-b", "error": "no usable tasks", "tasks": 0},
        ],
    }
    md = render_report(art)
    tuned_section = md.split("### Held-out")[0]
    assert "Composite mean: n/a" in tuned_section
    assert "Judge mean: n/a" in tuned_section
    assert "Objective mean: n/a" in tuned_section
    assert "Scored repos: 0, 2 skipped" in tuned_section
    # the held-out partition, which did score, is unaffected
    assert "Composite mean: 0.650" in md.split("### Held-out")[1]


def test_generalization_inspect_verdict_when_gap_exceeds_threshold():
    art = _generalization()
    art["generalization_gap"] = 0.15
    md = render_report(art)
    assert "Verdict: inspect" in md


def test_render_error_shape():
    md = render_report({"error": "no usable tasks", "tasks": 0})
    assert "# Benchmark report (error)" in md
    assert "no usable tasks" in md
    assert "Tasks: 0" in md


def test_render_unknown_for_non_dict():
    md = render_report("not a dict")
    assert "# Benchmark report (unknown)" in md


def test_render_tolerates_missing_optional_fields():
    md = render_report({"composite_mean": 0.5})
    assert "Composite mean: 0.500" in md
    assert "Judge mean: n/a" in md
    assert "Judge W-L-T: n/a" in md


def test_render_tolerates_malformed_per_repo_rows(caplog):
    art = _multi_repo()
    art["per_repo"] = [{"repo_path": "/ok", "composite_mean": 0.4, "tasks": 1}, "bad"]
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "| /ok | 0.400 | 1 |" in md
    assert "| n/a | n/a | n/a |" not in md
    assert any("per_repo[1] is str" in r.message for r in caplog.records)


# --- #667: per_repo hardening (resubmit of #668) -------------------------------------

_MALFORMED_PER_REPO = [42, 3.14, True, {"repo_path": "/x"}, "not a list"]


def test_per_repo_rows_accepts_only_real_lists():
    rows = [{"repo_path": "/a", "composite_mean": 0.5, "tasks": 1}]
    for bad in _MALFORMED_PER_REPO:
        assert _per_repo_rows(bad) == [], bad
    assert _per_repo_rows(rows) == rows
    assert _per_repo_rows(None) == []
    assert _per_repo_rows([]) == []


def test_per_repo_rows_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        assert _per_repo_rows(None) == []
    assert not caplog.records


def test_per_repo_rows_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        assert _per_repo_rows([]) == []
    assert not caplog.records


def test_per_repo_rows_warns_for_skipped_rows(caplog):
    mixed = [42, {"repo_path": "/a", "composite_mean": 0.5, "tasks": 1}]
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        assert len(_per_repo_rows(mixed)) == 1
    assert any("per_repo[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_per_repo_rows_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        assert _per_repo_rows(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("per_repo[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_is_multi_repo_requires_aggregate_fields():
    assert _is_multi_repo(_multi_repo()) is True
    assert _is_multi_repo(_single_repo()) is False
    assert _is_multi_repo({"composite_mean": 0.5, "repos": 2}) is False
    assert _is_multi_repo({"composite_mean": "bad", "repos": 2, "scored_repos": 1}) is True
    assert _is_multi_repo({"composite_mean": 0.5, "tasks": 3, "repos": 2, "scored_repos": 2}) is False


def test_render_multi_repo_with_non_list_per_repo_uses_multi_template():
    for bad in _MALFORMED_PER_REPO:
        art = {**_multi_repo(), "per_repo": bad}
        md = render_report(art)
        assert "# Benchmark report (multi-repo)" in md, bad
        assert "Repos: 2/2 scored" in md, bad
        assert "### Per-repo" not in md, bad


def test_render_multi_repo_with_empty_per_repo_omits_table(caplog):
    art = {**_multi_repo(), "per_repo": []}
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "# Benchmark report (multi-repo)" in md
    assert "### Per-repo" not in md
    assert not caplog.records


def test_render_multi_repo_with_all_junk_per_repo_omits_table(caplog):
    art = {**_multi_repo(), "per_repo": [42, "bad", None]}
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "# Benchmark report (multi-repo)" in md
    assert "### Per-repo" not in md
    assert any("no usable rows" in r.message for r in caplog.records)


def test_render_generalization_warns_for_non_list_partition_per_repo(caplog):
    art = _generalization()
    art["tuned"]["per_repo"] = 42
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "### Tuned" in md
    assert "| held-b | 0.650 | 2 |" in md
    assert any("per_repo is int" in r.message for r in caplog.records)


def test_composite_parts_dict_warns_for_non_object(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        parts = _composite_parts_dict({"composite_parts": 42})
    assert parts == {}
    assert any("composite_parts is int" in r.message for r in caplog.records)


def test_render_tolerates_malformed_composite_parts(caplog):
    art = _single_repo()
    art["composite_parts"] = 42
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "Judge mean: n/a" in md
    assert "Objective mean: n/a" in md
    assert any("composite_parts is int" in r.message for r in caplog.records)


def test_render_does_not_mutate_artifact():
    art = _generalization()
    snapshot = copy.deepcopy(art)
    render_report(art)
    assert art == snapshot


# --- non-finite (NaN/Infinity) numeric fields render n/a instead of raising (#616) --------


def test_fmt_score_and_fmt_rate_render_non_finite_as_na():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _fmt_score(bad) == "n/a"
        assert _fmt_rate(bad) == "n/a"
    # finite values still format normally
    assert _fmt_score(0.65) == "0.650"
    assert _fmt_rate(0.25) == "25.0%"


def test_render_single_repo_renders_na_for_non_finite_fields():
    art = _single_repo()
    art["composite_mean"] = float("nan")
    art["composite_parts"] = {"judge_mean": float("inf"), "objective_mean": float("-inf")}
    art["weights"] = {"judge": float("nan"), "objective": 0.4}
    art["judge_report"] = {
        "wins": float("nan"),
        "losses": 1,
        "ties": 0,
        "disagreement_rate": float("inf"),
    }
    art["tasks"] = float("nan")
    md = render_report(art)
    assert "# Benchmark report (single-repo)" in md
    assert "Composite mean: n/a" in md
    assert "Judge mean: n/a" in md
    assert "Objective mean: n/a" in md
    assert "Weights: judge n/a, objective 0.400" in md
    assert "Judge W-L-T: n/a" in md
    assert "Order disagreement rate: n/a" in md
    # a non-finite tasks count is omitted, exactly like a wrong-typed one
    assert "Tasks:" not in md


def test_render_single_repo_survives_issue_repro():
    # the exact repro from #616: previously ValueError from int(float("nan"))
    md = render_report({"composite_mean": 0.5, "tasks": float("nan")})
    assert "Composite mean: 0.500" in md
    assert "Tasks:" not in md


def test_render_multi_repo_survives_non_finite_counts():
    # non-finite aggregate counts are not a trusted multi-repo shape (#667); render as
    # single-repo without crashing (#616).
    md = render_report(
        {"composite_mean": 0.5, "per_repo": [],
         "scored_repos": float("inf"), "repos": float("inf")}
    )
    assert "# Benchmark report (single-repo)" in md
    assert "Composite mean: 0.500" in md
    assert "Repos:" not in md


def test_render_multi_repo_skips_non_finite_scored_and_skipped_details():
    art = _multi_repo()
    art["skipped"] = float("inf")
    md = render_report(art)
    # repos and scored_repos are finite; only the malformed skipped count is omitted
    repo_lines = [line for line in md.splitlines() if line.startswith("- Repos:")]
    assert repo_lines == ["- Repos: 2/2 scored"]


def test_render_multi_repo_rejects_non_finite_scored_repos_shape():
    art = _multi_repo()
    art["scored_repos"] = float("nan")
    art["skipped"] = float("inf")
    md = render_report(art)
    # non-finite scored_repos is not a trusted multi-repo aggregate (#667)
    assert "# Benchmark report (single-repo)" in md
    assert "Repos:" not in md


def test_per_repo_table_renders_na_for_non_finite_cells():
    art = _multi_repo()
    art["per_repo"][0]["composite_mean"] = float("nan")
    art["per_repo"][0]["tasks"] = float("inf")
    md = render_report(art)
    assert "| /a | n/a | n/a |" in md
    # the well-formed sibling row is unaffected
    assert "| /b | 0.650 | 3 |" in md


def test_generalization_verdict_is_na_for_non_finite_gap():
    # float("inf") > threshold is True and float("-inf") > threshold is False, so an
    # unguarded comparison would fabricate an "inspect"/"pass" verdict from garbage.
    for bad in (float("nan"), float("inf"), float("-inf")):
        art = _generalization()
        art["generalization_gap"] = bad
        md = render_report(art)
        assert "Generalization gap (tuned − held-out): n/a" in md
        assert "Verdict: n/a" in md
        assert "Verdict: inspect" not in md
        assert "Verdict: pass" not in md


def test_render_partition_renders_na_for_non_finite_fields():
    art = _generalization()
    art["tuned"]["composite_mean"] = float("nan")
    art["tuned"]["scored_repos"] = float("inf")
    md = render_report(art)
    tuned_section = md.split("### Held-out")[0]
    assert "Composite mean: n/a" in tuned_section
    assert "Scored repos:" not in tuned_section
    # the well-formed held-out partition still renders its real values
    assert "Composite mean: 0.650" in md.split("### Held-out")[1]


def test_render_error_shape_omits_non_finite_tasks():
    md = render_report({"error": "boom", "tasks": float("nan")})
    assert "# Benchmark report (error)" in md
    assert "Tasks:" not in md


def test_render_tolerates_int_counts_too_large_for_float():
    # json.load happily parses arbitrarily large integer literals; float-formatting one
    # raises OverflowError, so it is treated as malformed like a non-finite float.
    art = _single_repo()
    art["judge_report"]["wins"] = 10**400
    md = render_report(art)
    assert "Judge W-L-T: n/a" in md


def test_load_artifact_round_trip(tmp_path):
    path = tmp_path / "result.json"
    payload = _single_repo()
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert load_artifact(str(path)) == payload


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.report", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_reports_a_clean_error_for_oversized_int_literal(tmp_path):
    # json.load raises a plain ValueError (not JSONDecodeError) for an oversized int
    # literal (py3.11+); the CLI must exit 1 with a clean message (#1692).
    path = tmp_path / "huge.json"
    path.write_text('{"composite_mean": ' + "9" * 5000 + "}", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not valid JSON" in result.stderr
    assert "UTF-8" not in result.stderr
    assert str(path) in result.stderr


def test_cli_reports_a_clean_error_for_non_utf8_file(tmp_path):
    # Non-UTF-8 mid-read raises UnicodeDecodeError (a ValueError subclass); keep the
    # distinct UTF-8 message rather than letting it fall through as a traceback (#1692).
    path = tmp_path / "latin1.json"
    path.write_bytes(b'{"composite_mean": 0.5, "x": \xff}')
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not valid UTF-8 JSON" in result.stderr
    assert str(path) in result.stderr


def test_cli_directory_path_reports_clean_error(tmp_path):
    # A directory passed where a file is expected makes open() raise IsADirectoryError;
    # the CLI must report it cleanly, not dump a raw traceback (#612). Uses a real
    # directory rather than patching open(), so no global builtins side effects.
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "directory" in result.stderr


@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root bypasses file-permission bits, so an unreadable file cannot be simulated",
)
def test_cli_unreadable_file_reports_clean_error(tmp_path):
    # A real file with its read bit cleared makes open() raise PermissionError; the CLI
    # must report it cleanly. Real chmod, no monkeypatching of builtins.open.
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")
    os.chmod(path, 0)
    try:
        result = _run_cli(str(path))
    finally:
        os.chmod(path, 0o644)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "not readable" in result.stderr


def test_cli_still_renders_a_well_formed_artifact(tmp_path):
    path = tmp_path / "good.json"
    path.write_text(json.dumps(_single_repo()), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert "# Benchmark report (single-repo)" in result.stdout


def test_cli_renders_a_non_finite_artifact_without_traceback(tmp_path):
    # end-to-end reachability for #616: run_eval --out serializes NaN/Infinity via
    # json.dump, json.load parses them back, and the report CLI must render the reloaded
    # artifact instead of aborting.
    payload = _single_repo()
    payload["tasks"] = float("nan")
    payload["judge_report"]["disagreement_rate"] = float("inf")
    path = tmp_path / "nonfinite.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
    assert "# Benchmark report (single-repo)" in result.stdout
    assert "Order disagreement rate: n/a" in result.stdout
