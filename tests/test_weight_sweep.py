"""Tests for the judge/objective weight-sweep helper (#53) — deterministic, offline."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.runner import WEIGHT_SWEEP_GRID, weight_sweep  # noqa: E402
from benchmark.score import composite_score  # noqa: E402

# A tiny per-task shape mirroring run_replay's `rows`: a judge `winner` plus an `objective`
# dict. objective_component reduces the objective to a scalar in [0, 1]; here module_recall is
# the only signal so the anchor equals it.
ROWS = [
    {"winner": "challenger", "objective": {"module_recall": 1.0}},   # judge 1.0, anchor 1.0
    {"winner": "baseline", "objective": {"module_recall": 0.0}},     # judge 0.0, anchor 0.0
    {"winner": "tie", "objective": {"module_recall": 0.5}},          # judge 0.5, anchor 0.5
]


def test_weight_sweep_default_grid_shape():
    sweep = weight_sweep(ROWS)
    assert [(r["w_judge"], r["w_objective"]) for r in sweep] == list(WEIGHT_SWEEP_GRID)
    for row in sweep:
        assert set(row) == {"w_judge", "w_objective", "composite_mean"}
        assert 0.0 <= row["composite_mean"] <= 1.0


def test_weight_sweep_matches_composite_score_at_each_grid_point():
    # The sweep must re-blend exactly as composite_score does, so at every weight pair the
    # swept mean equals averaging composite_score over the same tasks.
    winners = {"challenger": "A", "baseline": "B", "tie": "tie"}
    sweep = weight_sweep(ROWS)
    for row in sweep:
        wj, wo = row["w_judge"], row["w_objective"]
        expected = round(
            sum(composite_score(winners[r["winner"]], r["objective"], wj, wo) for r in ROWS)
            / len(ROWS),
            3,
        )
        assert row["composite_mean"] == expected


def test_weight_sweep_reproduces_run_composite_mean_at_production_weights():
    # Sweeping at the production default (0.6 / 0.4) must reproduce what run_replay reports,
    # so the helper is a faithful re-blend rather than a separate scoring path.
    default = next(r for r in weight_sweep(ROWS, grid=[(0.6, 0.4)]))
    winners = {"challenger": "A", "baseline": "B", "tie": "tie"}
    run_mean = round(
        sum(composite_score(winners[r["winner"]], r["objective"], 0.6, 0.4) for r in ROWS)
        / len(ROWS),
        3,
    )
    assert default["composite_mean"] == run_mean


def test_weight_sweep_shifts_toward_the_favored_component():
    # A run the challenger wins on judging but loses on the objective anchor should score
    # higher as weight moves toward the judge, and lower as it moves toward the objective.
    rows = [{"winner": "challenger", "objective": {"module_recall": 0.0}}]  # judge 1.0, anchor 0.0
    judge_heavy = weight_sweep(rows, grid=[(0.8, 0.2)])[0]["composite_mean"]
    objective_heavy = weight_sweep(rows, grid=[(0.2, 0.8)])[0]["composite_mean"]
    assert judge_heavy > objective_heavy


def test_weight_sweep_empty_rows_is_zero_not_a_crash():
    for row in weight_sweep([]):
        assert row["composite_mean"] == 0.0
    # Rows with an unrecognized winner contribute nothing rather than raising.
    assert weight_sweep([{"winner": "???", "objective": {}}])[0]["composite_mean"] == 0.0
