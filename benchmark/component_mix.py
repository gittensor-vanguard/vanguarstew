"""Summarize judge versus objective blend fractions from composite_parts.

``composite_spread`` reports the delta between component means; this utility normalizes them into
judge/objective fractions for CI dashboards, with per-partition detail for generalization artifacts.

Pure analysis: no I/O, never mutates its input, and missing parts yield ``None`` rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _round3(value) -> float | None:
    if not _is_number(value):
        return None
    return round(float(value), 3)


def _mix_from_parts(parts) -> dict:
    if not isinstance(parts, dict):
        if parts is not None:
            logger.warning(
                "component_mix: composite_parts is %s, not an object; treating as empty",
                type(parts).__name__,
            )
        return {
            "judge_mean": None,
            "objective_mean": None,
            "judge_fraction": None,
            "objective_fraction": None,
        }
    judge = _round3(parts.get("judge_mean"))
    objective = _round3(parts.get("objective_mean"))
    if judge is None or objective is None:
        return {
            "judge_mean": judge,
            "objective_mean": objective,
            "judge_fraction": None,
            "objective_fraction": None,
        }
    total = judge + objective
    if total == 0 or not math.isfinite(total):
        # Each of judge/objective is individually finite (checked above), but their SUM can
        # still overflow to inf for two finite values near the top of the float range -- a
        # plain `total == 0` check doesn't catch that, and dividing by an infinite total
        # silently yields a fabricated 0.0/0.0 instead of failing closed like every other
        # edge case here.
        return {
            "judge_mean": judge,
            "objective_mean": objective,
            "judge_fraction": None,
            "objective_fraction": None,
        }
    judge_fraction = round(judge / total, 3)
    return {
        "judge_mean": judge,
        "objective_mean": objective,
        "judge_fraction": judge_fraction,
        "objective_fraction": round(objective / total, 3),
    }


def _slice_mix(slice_) -> dict:
    return _mix_from_parts(_dict(slice_).get("composite_parts"))


def summarize_component_mix(artifact) -> dict:
    """Return judge/objective blend fractions for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _dict(artifact.get("tuned"))
        held_out = _dict(artifact.get("held_out"))
        partitions = {
            "tuned": _slice_mix(tuned),
            "held_out": _slice_mix(held_out),
        }
        return {
            "kind": kind,
            **_slice_mix(tuned),
            "partitions": partitions,
        }
    return {
        "kind": kind,
        **_slice_mix(artifact),
        "partitions": None,
    }


def _fmt_fraction(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def component_mix_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_component_mix` result."""
    summary = _dict(summary)
    if summary.get("kind") == "generalization":
        parts = _dict(summary.get("partitions"))
        tuned = _dict(parts.get("tuned"))
        held = _dict(parts.get("held_out"))
        return (
            f"component mix: judge {_fmt_fraction(summary.get('judge_fraction'))} "
            f"[tuned {_fmt_fraction(tuned.get('judge_fraction'))}, "
            f"held-out {_fmt_fraction(held.get('judge_fraction'))}]"
        )
    return f"component mix: judge {_fmt_fraction(summary.get('judge_fraction'))}"
