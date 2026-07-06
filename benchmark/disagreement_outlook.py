"""Report pairwise judge disagreement outlook from a replay artifact.

``judge_gate`` pass/fails judge robustness; this read-only utility exposes ``disagreement_rate``
and ``dual_order_tasks`` for CI dashboards with a simple stable/unstable verdict.

Pure analysis: no I/O, never mutates its input, and non-finite or missing telemetry yields
``None`` fields rather than raising.
"""

from __future__ import annotations

import logging
import math

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)

DEFAULT_STABLE_THRESHOLD = 0.3


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _judge_telemetry(artifact: dict) -> dict:
    for source in (artifact.get("judge_report"), artifact.get("judge_order_stats")):
        if isinstance(source, dict):
            return source
    return {}


def _dual_order_tasks(telemetry: dict) -> int | None:
    value = telemetry.get("dual_order_tasks")
    return value if _is_int(value) and value >= 0 else None


def _disagreement_rate(telemetry: dict) -> float | None:
    value = telemetry.get("disagreement_rate")
    return round(float(value), 3) if _is_number(value) else None


def _verdict(rate: float | None, threshold: float) -> str | None:
    if not _is_number(rate):
        return None
    return "stable" if rate <= threshold else "unstable"


def summarize_disagreement_outlook(artifact, stable_threshold: float = DEFAULT_STABLE_THRESHOLD) -> dict:
    """Return disagreement telemetry and outlook for a replay ``artifact``."""
    artifact = _dict(artifact)
    telemetry = _judge_telemetry(artifact)
    dual = _dual_order_tasks(telemetry)
    rate = _disagreement_rate(telemetry)
    threshold = float(stable_threshold) if _is_number(stable_threshold) else DEFAULT_STABLE_THRESHOLD
    return {
        "kind": artifact_kind(artifact),
        "dual_order_tasks": dual,
        "disagreement_rate": rate,
        "verdict": _verdict(rate, threshold),
        "stable_threshold": threshold,
    }


def disagreement_outlook_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_disagreement_outlook` result."""
    summary = _dict(summary)
    rate = summary.get("disagreement_rate")
    rate_txt = f"{float(rate):.1%}" if _is_number(rate) else "n/a"
    verdict = summary.get("verdict") or "unknown"
    dual = summary.get("dual_order_tasks")
    dual_txt = str(dual) if _is_int(dual) else "n/a"
    return f"disagreement outlook: {verdict} (rate {rate_txt}, {dual_txt} dual-order task(s))"
