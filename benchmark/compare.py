"""Compare saved replay result artifacts (from ``scripts.run_eval --out``).

Supports single-repo, multi-repo, and generalization-shaped results. Older artifacts
missing optional fields (e.g. ``judge_report``) degrade gracefully.
"""

from __future__ import annotations

import json


def _num(value):
    """Return a float when ``value`` is numeric, else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _delta(baseline, candidate):
    """Candidate minus baseline when both sides are numeric, else None."""
    b, c = _num(baseline), _num(candidate)
    if b is None or c is None:
        return None
    return round(c - b, 3)


def _composite_block(result: dict) -> dict:
    parts = result.get("composite_parts") or {}
    return {
        "composite_mean": result.get("composite_mean"),
        "judge_mean": parts.get("judge_mean"),
        "objective_mean": parts.get("objective_mean"),
    }


def _judge_block(result: dict) -> dict | None:
    report = result.get("judge_report")
    if not isinstance(report, dict):
        return None
    return {
        "wins": report.get("wins"),
        "losses": report.get("losses"),
        "ties": report.get("ties"),
        "disagreement_rate": report.get("disagreement_rate"),
    }


def _repo_key(entry: dict) -> str:
    for key in ("repo_name", "repo", "name"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return "unknown"


def _per_repo_composites(result: dict) -> dict[str, float | None]:
    per_repo = result.get("per_repo")
    if not isinstance(per_repo, list):
        return {}
    out = {}
    for entry in per_repo:
        if isinstance(entry, dict):
            out[_repo_key(entry)] = entry.get("composite_mean")
    return out


def _diff_named_maps(baseline: dict, candidate: dict) -> dict:
    keys = sorted(set(baseline) | set(candidate))
    return {
        key: _delta(baseline.get(key), candidate.get(key))
        for key in keys
        if _delta(baseline.get(key), candidate.get(key)) is not None
    }


def compare_results(baseline: dict, candidate: dict) -> dict:
    """Return a structured diff between two replay artifacts."""
    base_comp = _composite_block(baseline)
    cand_comp = _composite_block(candidate)
    composite = {
        "baseline": base_comp,
        "candidate": cand_comp,
        "delta": {
            "composite_mean": _delta(base_comp["composite_mean"], cand_comp["composite_mean"]),
            "judge_mean": _delta(base_comp["judge_mean"], cand_comp["judge_mean"]),
            "objective_mean": _delta(base_comp["objective_mean"], cand_comp["objective_mean"]),
        },
    }

    base_judge = _judge_block(baseline)
    cand_judge = _judge_block(candidate)
    judge = None
    if base_judge or cand_judge:
        base_judge = base_judge or {}
        cand_judge = cand_judge or {}
        judge = {
            "baseline": base_judge,
            "candidate": cand_judge,
            "delta": {
                "wins": _delta(base_judge.get("wins"), cand_judge.get("wins")),
                "losses": _delta(base_judge.get("losses"), cand_judge.get("losses")),
                "ties": _delta(base_judge.get("ties"), cand_judge.get("ties")),
                "disagreement_rate": _delta(
                    base_judge.get("disagreement_rate"), cand_judge.get("disagreement_rate")
                ),
            },
        }

    per_repo = _diff_named_maps(_per_repo_composites(baseline), _per_repo_composites(candidate))

    gap = None
    if "generalization_gap" in baseline or "generalization_gap" in candidate:
        gap = {
            "baseline": baseline.get("generalization_gap"),
            "candidate": candidate.get("generalization_gap"),
            "delta": _delta(baseline.get("generalization_gap"), candidate.get("generalization_gap")),
        }

    return {
        "composite": composite,
        "judge": judge,
        "per_repo_composite_delta": per_repo or None,
        "generalization_gap": gap,
    }


def compare_headline(diff: dict) -> str:
    """One-line human summary for stderr."""
    delta = (diff.get("composite") or {}).get("delta") or {}
    mean = delta.get("composite_mean")
    if mean is None:
        return "compare: no composite_mean delta available"
    sign = "+" if mean > 0 else ""
    parts = [f"composite_mean {sign}{mean:.3f}"]
    judge_delta = ((diff.get("judge") or {}).get("delta") or {}).get("disagreement_rate")
    if judge_delta is not None:
        jsign = "+" if judge_delta > 0 else ""
        parts.append(f"disagreement_rate {jsign}{judge_delta:.3f}")
    return "compare: " + "; ".join(parts)


def load_result(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object at the top level")
    return data
