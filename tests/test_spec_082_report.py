"""Characterization tests for Spec 082 — the benchmark report rendering contract.

These pin the observable behaviour of :func:`benchmark.report.render_report` (the Markdown view
of a saved ``run_eval --out`` artifact) so the Spec 082 acceptance criteria have executable teeth.
``tests/test_report.py`` already exercises the renderer in breadth; this suite is scoped to the
Spec 082 acceptance criteria: shape-dispatch precedence, the generalization verdict, the
``n/a``-over-crash/fabrication degradations, and purity. Every asserted value was read off the
live module, not hand-derived.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import render_report  # noqa: E402


def _single_repo():
    return {
        "tasks": 3,
        "composite_mean": 0.65,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.55},
        "judge_report": {"wins": 2, "losses": 1, "ties": 0, "disagreement_rate": 0.25},
    }


def _multi_repo():
    return {
        "repos": 2,
        "scored_repos": 2,
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": 0.65, "objective_mean": 0.5},
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
        },
        "held_out": {
            "scored_repos": 1,
            "composite_mean": 0.65,
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        },
    }


# ---- AC-1: shape dispatch precedence --------------------------------------------------------


def test_dispatch_prefers_generalization_over_error():
    art = _generalization()
    art["error"] = "should be ignored by shape dispatch"
    md = render_report(art)
    assert md.startswith("# Benchmark report (generalization)")


def test_dispatch_prefers_multi_repo_over_single_repo():
    md = render_report(_multi_repo())
    assert md.startswith("# Benchmark report (multi-repo)")
    assert "# Benchmark report (single-repo)" not in md


def test_unknown_shape_for_non_dict_input():
    for bad in ("not a dict", 42, [1, 2, 3], None):
        assert render_report(bad) == "# Benchmark report (unknown)\n\n- Could not recognize artifact shape.\n"


def test_unknown_shape_for_dict_matching_nothing():
    assert render_report({}).startswith("# Benchmark report (unknown)")
    assert render_report({"some_other_field": 1}).startswith("# Benchmark report (unknown)")


# ---- AC-2: composite_mean outranks a stray error field ---------------------------------------


def test_single_repo_with_stray_error_still_renders_single_repo():
    art = _single_repo()
    art["error"] = "transient warning"
    md = render_report(art)
    assert md.startswith("# Benchmark report (single-repo)")
    assert "Status: error (transient warning)" in md
    assert "Composite mean: 0.650" in md


def test_multi_repo_with_stray_error_still_renders_multi_repo():
    art = _multi_repo()
    art["error"] = "transient warning"
    md = render_report(art)
    assert md.startswith("# Benchmark report (multi-repo)")
    assert "Composite mean: 0.600" in md


# ---- AC-3: generalization verdict -------------------------------------------------------------


def test_generalization_verdict_pass_and_inspect():
    passing = render_report(_generalization())
    assert "Verdict: pass" in passing

    art = _generalization()
    art["generalization_gap"] = 0.15
    inspecting = render_report(art)
    assert "Verdict: inspect" in inspecting


def test_generalization_verdict_respects_custom_threshold():
    art = _generalization()
    art["generalization_gap"] = 0.15
    assert "Verdict: pass" in render_report(art, gap_inspect_threshold=0.2)

    art["generalization_gap"] = 0.25
    assert "Verdict: inspect" in render_report(art, gap_inspect_threshold=0.2)


def test_generalization_verdict_is_na_for_non_numeric_gap():
    for bad in (None, float("nan"), float("inf"), float("-inf"), "bad"):
        art = _generalization()
        art["generalization_gap"] = bad
        md = render_report(art)
        assert "Generalization gap (tuned − held-out): n/a" in md
        assert "Verdict: n/a" in md


# ---- AC-4: non-finite / oversized numeric fields render n/a -----------------------------------


def test_non_finite_composite_and_judge_fields_render_na():
    art = _single_repo()
    art["composite_mean"] = float("nan")
    art["composite_parts"] = {"judge_mean": float("inf"), "objective_mean": float("-inf")}
    art["judge_report"]["disagreement_rate"] = float("nan")
    md = render_report(art)
    assert "Composite mean: n/a" in md
    assert "Judge mean: n/a" in md
    assert "Objective mean: n/a" in md
    assert "Order disagreement rate: n/a" in md


def test_oversized_int_field_renders_na():
    art = _single_repo()
    art["judge_report"]["wins"] = 10**400
    md = render_report(art)
    assert "Judge W-L-T: n/a" in md


# ---- AC-5: an unscored partition renders n/a, not its placeholder 0.0 -------------------------


def test_unscored_partition_renders_na_not_placeholder_zero():
    art = _generalization()
    art["tuned"] = {
        "scored_repos": 0,
        "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    md = render_report(art)
    tuned_section = md.split("### Held-out")[0]
    assert "Composite mean: n/a" in tuned_section
    assert "Judge mean: n/a" in tuned_section
    assert "Objective mean: n/a" in tuned_section
    # the held-out partition, which did score, is unaffected
    assert "Composite mean: 0.650" in md.split("### Held-out")[1]


# ---- AC-6: malformed per_repo degrades to no table, with a warning ----------------------------


def test_non_list_per_repo_omits_table_with_warning(caplog):
    art = {**_multi_repo(), "per_repo": 42}
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert md.startswith("# Benchmark report (multi-repo)")
    assert "### Per-repo" not in md
    assert any("per_repo is int" in r.message for r in caplog.records)


def test_all_junk_per_repo_omits_table_with_warning(caplog):
    art = {**_multi_repo(), "per_repo": [42, "bad", None]}
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "### Per-repo" not in md
    assert any("no usable rows" in r.message for r in caplog.records)


def test_absent_or_empty_per_repo_omits_table_silently(caplog):
    for per_repo in (None, []):
        art = {**_multi_repo()}
        if per_repo is None:
            art.pop("per_repo", None)
        else:
            art["per_repo"] = per_repo
        with caplog.at_level(logging.WARNING, logger="benchmark.report"):
            md = render_report(art)
        assert "### Per-repo" not in md
        assert not caplog.records


# ---- AC-7: malformed composite_parts/foresight warn; a missing/bad judge_report is silent -----


def test_malformed_composite_parts_warns_and_degrades(caplog):
    art = _single_repo()
    art["composite_parts"] = 42
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "Judge mean: n/a" in md
    assert "Objective mean: n/a" in md
    assert any("composite_parts is int" in r.message for r in caplog.records)


def test_malformed_foresight_warns_and_degrades(caplog):
    art = _single_repo()
    art["foresight"] = "not-a-dict"
    with caplog.at_level(logging.WARNING, logger="benchmark.report"):
        md = render_report(art)
    assert "Foresight — modules: n/a (n=0), kinds: n/a (n=0), release: n/a (n=0), bump level: n/a (n=0)" in md
    assert any("foresight is str" in r.message for r in caplog.records)


def test_missing_or_malformed_judge_report_is_silent_na(caplog):
    for judge_report in (None, 42, "bad"):
        art = _single_repo()
        if judge_report is None:
            art.pop("judge_report", None)
        else:
            art["judge_report"] = judge_report
        with caplog.at_level(logging.WARNING, logger="benchmark.report"):
            md = render_report(art)
        assert "Judge W-L-T: n/a" in md
        assert "Order disagreement rate: n/a" in md
        assert not caplog.records


# ---- AC-8: purity -------------------------------------------------------------------------


def test_render_report_does_not_mutate_any_shape():
    for art in (_single_repo(), _multi_repo(), _generalization(), {"error": "boom"}, "not a dict"):
        before = copy.deepcopy(art)
        render_report(art)
        assert art == before
