"""Tests for the judge/objective weight-sweep helper (#53) — deterministic, offline."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.runner import (  # noqa: E402
    WEIGHT_SWEEP_GRID,
    _freeze_window_dict,
    _rows_list,
    _sweep_rows,
    weight_sweep,
)
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


# --- #561: a non-list rows container must not abort weight_sweep --------------------

_MALFORMED_ROWS = [42, 3.14, True, {"winner": "challenger"}, "not a list"]


def test_sweep_rows_accepts_only_real_lists():
    for bad in _MALFORMED_ROWS:
        assert _sweep_rows(bad) == [], bad
    assert _sweep_rows(ROWS) == ROWS
    assert _sweep_rows(None) == []


def test_weight_sweep_survives_non_list_rows():
    for bad in _MALFORMED_ROWS:
        sweep = weight_sweep(bad)
        assert len(sweep) == len(WEIGHT_SWEEP_GRID), bad
        assert all(row["composite_mean"] == 0.0 for row in sweep), bad


def test_weight_sweep_logs_warning_for_non_list_rows(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.runner"):
        sweep = weight_sweep(42)
    assert all(row["composite_mean"] == 0.0 for row in sweep)
    assert any("rows is int" in r.message for r in caplog.records)


# --- #597: non-list replay rows must not abort multi-repo judge aggregation -----------

def test_rows_list_accepts_only_real_lists():
    for bad in _MALFORMED_ROWS:
        assert _rows_list(bad, "replay rows") == [], bad
    assert _rows_list(ROWS, "replay rows") == ROWS
    assert _rows_list(None, "replay rows") == []


def test_multi_repo_judge_order_collection_survives_non_list_rows(caplog):
    import logging

    res = {"rows": 42, "tasks": 1, "composite_mean": 0.5}
    with caplog.at_level(logging.WARNING, logger="benchmark.runner"):
        orders = [
            row.get("judge_order")
            for row in _rows_list(res.get("rows"), "replay rows")
        ]
    assert orders == []
    assert any("replay rows is int" in r.message for r in caplog.records)


# --- #643: truthy non-dict freeze_window must not abort multi-repo replay --------------

_MALFORMED_FREEZE_WINDOWS = [42, 3.14, True, ["after"], "not a dict"]


def test_freeze_window_dict_accepts_only_real_dicts():
    good = {"min_history": 3, "rotation_seed": 5}
    for bad in _MALFORMED_FREEZE_WINDOWS:
        assert _freeze_window_dict(bad) == {}, bad
    assert _freeze_window_dict(good) == good
    assert _freeze_window_dict(None) == {}


def test_freeze_window_dict_missing_key_emits_no_warning(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.runner"):
        assert _freeze_window_dict(None) == {}
    assert not caplog.records


def test_freeze_window_dict_warns_for_non_dict_value(caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="benchmark.runner"):
        merged = {
            key: value
            for key, value in _freeze_window_dict(42).items()
        }
    assert merged == {}
    assert any("freeze_window is int" in r.message for r in caplog.records)
