"""CLI: compare two saved ``run_eval --out`` JSON artifacts.

  python -m scripts.compare_eval baseline.json candidate.json
"""

from __future__ import annotations

import argparse
import json
import sys


def _numeric(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _delta(candidate, baseline) -> float | None:
    c = _numeric(candidate)
    b = _numeric(baseline)
    if c is None or b is None:
        return None
    return round(c - b, 3)


def _metric_triplet(baseline: dict, candidate: dict, key: str) -> dict:
    base = baseline.get(key)
    cand = candidate.get(key)
    return {
        "baseline": base,
        "candidate": cand,
        "delta": _delta(cand, base),
    }


def _repo_key(entry: dict) -> str:
    for key in ("repo_path", "url", "repo", "name"):
        value = entry.get(key)
        if value:
            return str(value)
    freeze = entry.get("freeze_commit")
    if isinstance(freeze, str) and freeze:
        return freeze[:10]
    return repr(sorted(entry.keys()))


def _per_repo_deltas(baseline: dict, candidate: dict) -> list[dict]:
    base_by_key = {_repo_key(row): row for row in baseline.get("per_repo") or []}
    out = []
    for row in candidate.get("per_repo") or []:
        key = _repo_key(row)
        base_row = base_by_key.get(key)
        if base_row is None:
            continue
        out.append({
            "repo": key,
            "composite_mean": _metric_triplet(base_row, row, "composite_mean"),
            "tasks": {
                "baseline": base_row.get("tasks"),
                "candidate": row.get("tasks"),
            },
        })
    return out


def compare_eval_artifacts(baseline: dict, candidate: dict) -> dict:
    """Return a stable JSON summary of how ``candidate`` differs from ``baseline``."""
    parts = {}
    base_parts = baseline.get("composite_parts") or {}
    cand_parts = candidate.get("composite_parts") or {}
    for key in ("judge_mean", "objective_mean"):
        if key in base_parts or key in cand_parts:
            parts[key] = _metric_triplet(base_parts, cand_parts, key)

    report = {}
    base_report = baseline.get("judge_report") or {}
    cand_report = candidate.get("judge_report") or {}
    if base_report or cand_report:
        for key in ("wins", "losses", "ties", "disagreement_rate"):
            if key in base_report or key in cand_report:
                report[key] = _metric_triplet(base_report, cand_report, key)

    result = {
        "composite_mean": _metric_triplet(baseline, candidate, "composite_mean"),
    }
    if parts:
        result["composite_parts"] = parts
    if report:
        result["judge_report"] = report
    per_repo = _per_repo_deltas(baseline, candidate)
    if per_repo:
        result["per_repo"] = per_repo
    return result


def comparison_headline(diff: dict) -> str:
    """One-line human summary for stderr."""
    mean = diff.get("composite_mean") or {}
    delta = mean.get("delta")
    if delta is None:
        return "compare_eval: composite_mean delta unavailable"
    direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
    return (
        f"compare_eval: composite_mean {mean.get('baseline')} -> {mean.get('candidate')} "
        f"({direction} {delta:+.3f})"
    )


def load_artifact(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"artifact must be a JSON object: {path}")
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two run_eval --out JSON artifacts")
    ap.add_argument("baseline", help="earlier or reference result JSON")
    ap.add_argument("candidate", help="newer or candidate result JSON")
    args = ap.parse_args()
    diff = compare_eval_artifacts(load_artifact(args.baseline), load_artifact(args.candidate))
    print(comparison_headline(diff), file=sys.stderr)
    print(json.dumps(diff, indent=2))


if __name__ == "__main__":
    main()
