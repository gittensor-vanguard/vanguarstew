"""Contract tests for specs/002-scoring-anchor (composition) — assert benchmark.score
objective_component/composite_score satisfy the spec's composition EARS criteria: scalar bounds,
ranking-field selection, release/bump axes, and judge/objective blending. Offline, deterministic.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from benchmark.score import composite_score, objective_component  # noqa: E402


def _assert_unit_interval(value: float):
    assert isinstance(value, float)
    assert 0.0 <= value <= 1.0


# --- objective_component --------------------------------------------------------------------

def test_objective_component_is_bounded_in_zero_one():
    _assert_unit_interval(objective_component({"module_recall": 0.5}))
    _assert_unit_interval(objective_component({"module_recall": 1.0, "release_signaled": True,
                                                "release_predicted": True, "bump_actual": "minor",
                                                "bump_match": True}))


def test_objective_component_prefers_weighted_module_recall():
    obj = {"module_recall": 0.2, "weighted_module_recall": 0.8}
    assert objective_component(obj) == 0.8


def test_objective_component_counts_release_only_when_signaled():
    assert objective_component({"module_recall": 1.0, "release_signaled": False}) == 1.0
    assert objective_component({"module_recall": 1.0, "release_signaled": True,
                                "release_predicted": False}) == 0.5


def test_objective_component_counts_bump_only_when_bump_actual_known():
    base = {"module_recall": 1.0, "release_signaled": True, "release_predicted": True}
    assert objective_component({**base, "bump_actual": None}) == 1.0
    assert objective_component({**base, "bump_actual": "minor", "bump_match": False}) == round(2 / 3, 3)


def test_objective_component_excludes_backlog_and_trajectory_fields():
    base = {"module_recall": 0.4}
    assert objective_component(base) == 0.4
    assert objective_component({**base, "backlog_recall": 1.0}) == 0.4
    assert objective_component({**base, "trajectory_overlap": 0.99}) == 0.4


# --- composite_score ----------------------------------------------------------------------

@pytest.mark.parametrize("winner,expected_judge_term", [
    ("A", 1.0),
    ("tie", 0.5),
    ("B", 0.0),
])
def test_composite_score_maps_judge_outcomes(winner, expected_judge_term):
    obj = {"module_recall": 0.0}
    assert composite_score(winner, obj, w_judge=1.0, w_objective=0.0) == expected_judge_term


def test_composite_score_blends_judge_and_objective_at_default_weights():
    obj = {"module_recall": 1.0}
    assert composite_score("tie", obj) == 0.7   # 0.6*0.5 + 0.4*1.0
    assert composite_score("A", obj) == 1.0      # 0.6*1.0 + 0.4*1.0
    assert composite_score("B", obj) == 0.4      # 0.6*0.0 + 0.4*1.0


def test_composite_score_normalizes_non_unit_weights():
    obj = {"module_recall": 0.5}
    assert composite_score("tie", obj, w_judge=3.0, w_objective=1.0) == 0.5
