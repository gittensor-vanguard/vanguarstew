"""Characterization tests for Spec 082 — the Markdown report-rendering contract.

These pin the observable behaviour of :func:`benchmark.report.render_report` — the human-facing
view of a saved ``run_eval --out`` artifact — so the Spec 082 acceptance criteria have executable
teeth. Every asserted value was taken from the live module, not hand-computed.

The focus is the load-bearing invariants: the shape-dispatch precedence, and the "``n/a`` over a
crash or a fabricated number" degradations behind issues #616 (non-finite fields), #507 (unscored
placeholder), and #667 (non-list ``per_repo``). ``tests/test_report.py`` exercises the rendering
in breadth; this suite pins the contract those behaviours form.
"""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.report import (  # noqa: E402
    DEFAULT_GAP_INSPECT_THRESHOLD,
    render_report,
)


def _headline(md):
    return md.splitlines()[0]


def _line(md, prefix):
    return next((line for line in md.splitlines() if line.startswith(prefix)), None)


# ---- shape dispatch ------------------------------------------------------------------------


def test_single_repo_shape_renders_the_single_repo_headline_and_scores():
    art = {
        "tasks": 3, "baseline": "empty", "composite_mean": 0.65,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.55},
        "judge_report": {"wins": 2, "losses": 1, "ties": 0, "disagreement_rate": 0.25},
    }
    md = render_report(art)
    assert _headline(md) == "# Benchmark report (single-repo)"
    assert "- Composite mean: 0.650" in md
    assert "- Judge mean: 0.700" in md
    assert "- Objective mean: 0.550" in md
    assert "- Judge W-L-T: 2-1-0" in md
    assert "- Order disagreement rate: 25.0%" in md
    assert "- Tasks: 3" in md


def test_multi_repo_shape_renders_the_multi_repo_headline_and_repo_tally():
    art = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.6,
        "composite_parts": {"judge_mean": 0.65, "objective_mean": 0.5},
        "per_repo": [{"repo_path": "/a", "composite_mean": 0.55, "tasks": 2}],
    }
    md = render_report(art)
    assert _headline(md) == "# Benchmark report (multi-repo)"
    assert _line(md, "- Repos:") == "- Repos: 2/2 scored"
    assert "### Per-repo" in md


def test_generalization_shape_renders_gap_and_verdict():
    art = {
        "repo_set": "benchmark/repo_sets/curated.json", "generalization_gap": 0.05,
        "tuned": {"scored_repos": 1, "composite_mean": 0.7},
        "held_out": {"scored_repos": 1, "composite_mean": 0.65},
    }
    md = render_report(art)
    assert _headline(md) == "# Benchmark report (generalization)"
    assert "- Generalization gap (tuned − held-out): 0.050" in md
    assert "- Verdict: pass" in md
    assert "### Tuned" in md
    assert "### Held-out" in md


def test_error_shape_renders_the_error_headline():
    md = render_report({"error": "boom", "tasks": 0})
    assert _headline(md) == "# Benchmark report (error)"
    assert "- Error: boom" in md


def test_unknown_shape_for_empty_dict_and_non_dict():
    assert _headline(render_report({})) == "# Benchmark report (unknown)"
    assert _headline(render_report("not-a-dict")) == "# Benchmark report (unknown)"
    assert _headline(render_report(None)) == "# Benchmark report (unknown)"


def test_error_with_a_composite_mean_still_renders_as_a_scored_report_not_error():
    # An artifact that carries a real composite_mean is a scored report even if it also has a
    # stray `error` field — the composite branch wins over the error branch.
    md = render_report({"error": "warn", "composite_mean": 0.5})
    assert _headline(md) == "# Benchmark report (single-repo)"


# ---- verdict threshold ---------------------------------------------------------------------


def test_gap_verdict_flips_to_inspect_above_the_threshold():
    base = {
        "repo_set": "s", "tuned": {"scored_repos": 1, "composite_mean": 0.9},
        "held_out": {"scored_repos": 1, "composite_mean": 0.5},
    }
    assert "- Verdict: inspect" in render_report({**base, "generalization_gap": 0.2})
    assert "- Verdict: pass" in render_report({**base, "generalization_gap": 0.05})
    assert DEFAULT_GAP_INSPECT_THRESHOLD == 0.10


def test_gap_threshold_is_configurable():
    art = {
        "repo_set": "s", "generalization_gap": 0.08,
        "tuned": {"scored_repos": 1, "composite_mean": 0.7},
        "held_out": {"scored_repos": 1, "composite_mean": 0.62},
    }
    assert "- Verdict: pass" in render_report(art)  # default 0.10
    assert "- Verdict: inspect" in render_report(art, gap_inspect_threshold=0.05)


# ---- n/a over crash / fabrication ----------------------------------------------------------


def test_non_finite_numeric_fields_render_na_not_a_crash(caplog):
    # #616: NaN/Infinity survive a JSON round-trip but are not renderable numbers.
    art = {"composite_mean": float("nan"),
           "composite_parts": {"judge_mean": float("inf"), "objective_mean": 0.5}}
    md = render_report(art)
    assert "- Composite mean: n/a" in md
    assert "- Judge mean: n/a" in md
    assert "- Objective mean: 0.500" in md


def test_oversized_int_field_renders_na_not_a_crash():
    # An int too large for float() would crash the f-string float formatting; it degrades to n/a.
    md = render_report({"composite_mean": 10 ** 400})
    assert "- Composite mean: n/a" in md


def test_unscored_partition_renders_na_not_its_placeholder_zero():
    # #507: scored_repos == 0 means composite_mean 0.0 is a placeholder, not a real score.
    art = {"repos": 1, "scored_repos": 0, "composite_mean": 0.0,
           "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}}
    md = render_report(art)
    assert "- Composite mean: n/a" in md
    assert "- Judge mean: n/a" in md
    assert "- Objective mean: n/a" in md


def test_non_list_per_repo_degrades_to_no_table_with_a_warning(caplog):
    # #667: a non-list per_repo must not select the wrong template or crash.
    art = {"repos": 2, "scored_repos": 1, "composite_mean": 0.5, "per_repo": "not-a-list"}
    with caplog.at_level(logging.WARNING):
        md = render_report(art)
    assert "### Per-repo" not in md
    assert any("per_repo is str" in rec.message for rec in caplog.records)


def test_malformed_composite_parts_renders_na_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        md = render_report({"composite_mean": 0.5, "composite_parts": "not-a-dict"})
    assert "- Judge mean: n/a" in md
    assert "- Objective mean: n/a" in md
    assert any("composite_parts is str" in rec.message for rec in caplog.records)


def test_missing_judge_report_renders_na_wlt():
    md = render_report({"composite_mean": 0.5})
    assert "- Judge W-L-T: n/a" in md
    assert "- Order disagreement rate: n/a" in md


# ---- purity ---------------------------------------------------------------------------------


def test_render_report_does_not_mutate_its_input():
    art = {"composite_mean": 0.5, "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
           "per_repo": [{"repo_name": "a", "composite_mean": 0.5}]}
    import copy
    before = copy.deepcopy(art)
    render_report(art)
    assert art == before


def test_render_report_always_returns_a_trailing_newline_terminated_string():
    for art in ({}, {"composite_mean": 0.5}, {"error": "x"}, "bad"):
        md = render_report(art)
        assert isinstance(md, str)
        assert md.endswith("\n")
