"""Persistence + disagreement reporting for replay results (issue #134).

A replay result is the benchmark's artifact: ``run_replay`` / ``run_multi_replay``
return it and ``scripts/run_eval`` serializes it to JSON. Judge-instability
telemetry — the ``judge_order_stats`` block (``agree`` / ``disagree`` / ``tie``
counts, ``dual_order_tasks``, ``disagreement_rate``; see #89) — lives inside that
result when dual-order judging is enabled. This module makes that signal durable
across runs and surfaces a disagreement summary alongside win/tie outcomes, so a
maintainer can tell whether disagreement drifts after judge-prompt, model, or
benchmark changes.

Everything here degrades gracefully when the telemetry is **absent**: older
artifacts, single-order judging, and offline runs have no ``judge_order_stats``,
so the summary simply omits the disagreement line and the trend reports ``None``
rather than failing. That is what lets historical and new artifacts coexist.
"""

from __future__ import annotations

import json

# The judge-order telemetry block key (produced by #89). ``disagreement_rate`` is
# the canonical single-number signal; the counts give it context.
JUDGE_ORDER_STATS = "judge_order_stats"


def disagreement_rate(result) -> float | None:
    """A result's dual-order disagreement rate, or ``None`` when not measured.

    Returns ``None`` when the result predates the telemetry, used single-order
    judging, or ran offline (no dual-order tasks to disagree on).
    """
    if not isinstance(result, dict):
        return None
    stats = result.get(JUDGE_ORDER_STATS)
    if not isinstance(stats, dict):
        return None
    rate = stats.get("disagreement_rate")
    if rate is None:
        return None
    try:
        return float(rate)
    except (TypeError, ValueError):
        return None


def save_result(result, path) -> str:
    """Persist a replay result to ``path`` as stable JSON.

    The on-disk artifact is the canonical form later runs are compared against,
    so ``judge_order_stats`` round-trips unchanged when present and is simply
    absent when not. Keys are sorted for a deterministic diff across runs.
    """
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=True)
    return path


def load_result(path):
    """Load a persisted replay result.

    Tolerant of artifacts with or without ``judge_order_stats`` (older results,
    single-order, offline), so historical artifacts remain readable.
    """
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_summary(result) -> str:
    """Compact human summary of one replay result: outcomes, then disagreement.

    The disagreement line appears only when ``judge_order_stats`` is present and
    at least one dual-order task was judged, so historical / single-order /
    offline results summarize cleanly without it.
    """
    tally = result.get("tally") or {}
    parts = [
        f"tasks={result.get('tasks')}",
        f"challenger={tally.get('challenger', 0)}",
        f"baseline={tally.get('baseline', 0)}",
        f"tie={tally.get('tie', 0)}",
    ]
    if "composite_mean" in result:
        parts.append(f"composite_mean={result['composite_mean']}")
    out = "  ".join(parts)

    stats = result.get(JUDGE_ORDER_STATS)
    if isinstance(stats, dict) and stats.get("dual_order_tasks"):
        out += (
            f"\njudge: agree={stats.get('agree', 0)}"
            f" disagree={stats.get('disagree', 0)}"
            f" tie={stats.get('tie', 0)}"
            f"  disagreement_rate={stats.get('disagreement_rate')}"
        )
    return out


def format_run_summary(result) -> str:
    """Human summary for a top-level run result (single- or multi-repo).

    Multi-repo results carry ``per_repo`` rather than a top-level ``tally``; each
    scored repo is summarized on its own block so its disagreement line shows up
    alongside its win/tie outcomes.
    """
    if isinstance(result, dict) and "per_repo" in result:
        lines = [
            f"multi-repo: scored={result.get('scored_repos')}"
            f" skipped={result.get('skipped')}"
            f" composite_mean={result.get('composite_mean')}"
        ]
        for row in result.get("per_repo") or []:
            repo = row.get("repo")
            res = {k: v for k, v in row.items() if k != "repo"}
            lines.append(f"[{repo}]")
            lines.append("  " + format_summary(res).replace("\n", "\n  "))
        return "\n".join(lines)
    return format_summary(result)


def disagreement_trend(results) -> dict:
    """Disagreement signal across many stored runs.

    Returns ``{"runs": N, "disagreement_rates": [...], "mean_rate": float | None}``
    where each rate comes from a result's ``judge_order_stats`` (``None`` for runs
    without it). ``mean_rate`` averages only the runs that measured a rate, and is
    ``None`` when none did — so a historical mix never reports a misleading zero.
    """
    rates = [disagreement_rate(r) for r in results]
    measured = [r for r in rates if r is not None]
    mean = round(sum(measured) / len(measured), 3) if measured else None
    return {
        "runs": len(results),
        "disagreement_rates": rates,
        "mean_rate": mean,
    }
