"""Shared thresholds for generalization acceptance, promotion gate, and report verdict.

``check_generalization`` (``benchmark/generalization_gate.py``) is the **promotion** bar: it
blocks overfit runs from promotion. ``check_acceptance`` (``benchmark/acceptance.py``) is the
**milestone** bar for the M3/M4 acceptance run: it confirms the run completed clean with a
reasonable gap on enough held-out evidence. Both gates evaluate the same tuned-minus-held-out gap
against ``PROMOTION_MAX_GAP`` so a retune cannot apply to only one. Acceptance additionally
requires each partition to score (tuned: at least ``DEFAULT_MIN_SCORED_REPOS``; held-out: at
least ``DEFAULT_MIN_HELD_OUT_REPOS``).

``report.render_report`` flags gaps above ``PROMOTION_MAX_GAP`` as ``inspect``.
"""

from __future__ import annotations

PROMOTION_MAX_GAP = 0.1
DEFAULT_MIN_HELD_OUT_REPOS = 3
DEFAULT_MIN_SCORED_REPOS = 1
