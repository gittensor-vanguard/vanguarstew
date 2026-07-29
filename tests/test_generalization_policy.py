"""Tests for shared generalization policy constants (#2153)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.acceptance import (  # noqa: E402
    DEFAULT_MAX_GAP as ACCEPTANCE_MAX_GAP,
)
from benchmark.acceptance import (
    check_acceptance,
)
from benchmark.generalization_gate import (  # noqa: E402
    DEFAULT_MAX_GAP as GATE_MAX_GAP,
)
from benchmark.generalization_gate import (
    check_generalization,
)
from benchmark.generalization_policy import (  # noqa: E402
    DEFAULT_MIN_HELD_OUT_REPOS,
    PROMOTION_MAX_GAP,
)
from benchmark.report import DEFAULT_GAP_INSPECT_THRESHOLD  # noqa: E402


def _artifact(tuned=0.70, held=0.58, held_repos=4):
    return {
        "generalization_gap": round(tuned - held, 3),
        "tuned": {"composite_mean": tuned, "scored_repos": 5},
        "held_out": {"composite_mean": held, "scored_repos": held_repos,
                     "per_repo": [{"tasks": 2}] * held_repos},
    }


def test_promotion_max_gap_is_single_source_of_truth():
    assert PROMOTION_MAX_GAP == 0.1
    assert GATE_MAX_GAP is PROMOTION_MAX_GAP
    assert ACCEPTANCE_MAX_GAP is PROMOTION_MAX_GAP
    assert DEFAULT_GAP_INSPECT_THRESHOLD is PROMOTION_MAX_GAP


def test_gap_in_promotion_dead_zone_fails_both_gates():
    # Issue #2153: gap 0.12 used to pass acceptance (0.15) while failing the promotion gate (0.1).
    artifact = _artifact()
    assert check_generalization(artifact)["passed"] is False
    assert check_acceptance(artifact)["passed"] is False
    assert "gap_within_tolerance" in [
        c["name"] for c in check_generalization(artifact)["checks"] if not c["passed"]
    ]
    assert "gap_within_bound" in [
        c["name"] for c in check_acceptance(artifact)["checks"] if not c["passed"]
    ]


def test_single_held_out_repo_fails_acceptance():
    artifact = _artifact(held_repos=1)
    checks = {c["name"]: c for c in check_acceptance(artifact)["checks"]}
    assert checks["both_partitions_scored"]["passed"] is False
    assert f"min {DEFAULT_MIN_HELD_OUT_REPOS}" in checks["both_partitions_scored"]["detail"]
