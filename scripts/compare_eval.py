"""CLI: compare two saved ``run_eval --out`` JSON artifacts.

  python -m scripts.compare_eval baseline.json candidate.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys


def _numeric(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # json parses an arbitrarily long integer literal into a Python int, and float() raises
        # OverflowError for one too large to convert -- so an oversized composite_mean must be
        # treated as non-numeric here rather than crashing the whole comparison. Mirrors the
        # oversized-int guards merged across the codebase (repo_task_mean #1571, gap_outlook
        # #1479, skip_share #1502, acceptance, component_floor).
        try:
            number = float(value)
        except OverflowError:
            return None
        if math.isfinite(number):
            return number
    return None


def _is_scored_unavailable(artifact: dict) -> bool:
    """True when ``scored_repos`` is present and zero — ``composite_mean`` is a placeholder."""
    if not isinstance(artifact, dict):
        return False
    scored = artifact.get("scored_repos")
    return isinstance(scored, (int, float)) and not isinstance(scored, bool) and not scored


def _effective_composite_mean(artifact: dict):
    """Partition or aggregate composite mean, or ``None`` when nothing was scored."""
    if not isinstance(artifact, dict):
        return None
    if _is_scored_unavailable(artifact):
        return None
    return artifact.get("composite_mean")


def _effective_composite_parts(artifact: dict) -> dict:
    """The ``composite_parts`` (``judge_mean``/``objective_mean``), or an empty mapping when
    nothing was scored. The component means an unscored run reports are ``_mean([])`` placeholders
    of ``0.0`` — exactly like its placeholder ``composite_mean`` — so they must be masked the same
    way, or the diff self-contradicts (a ``None`` composite delta alongside a fabricated component
    drop). Mirrors :func:`_effective_composite_mean`."""
    if not isinstance(artifact, dict) or _is_scored_unavailable(artifact):
        return {}
    parts = artifact.get("composite_parts")
    return parts if isinstance(parts, dict) else {}


def _delta(candidate, baseline) -> float | None:
    c = _numeric(candidate)
    b = _numeric(baseline)
    if c is None or b is None:
        return None
    return round(c - b, 3)


def _metric_triplet(baseline: dict, candidate: dict, key: str) -> dict:
    if key == "composite_mean":
        base = _numeric(_effective_composite_mean(baseline))
        cand = _numeric(_effective_composite_mean(candidate))
    else:
        base = _numeric(baseline.get(key)) if isinstance(baseline, dict) else None
        cand = _numeric(candidate.get(key)) if isinstance(candidate, dict) else None
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


def _repo_rows(artifact: dict) -> list:
    """The ``per_repo`` table when it is a list of dict rows, else empty (#464).

    A truthy non-list (a malformed artifact) must not reach ``for row in ...`` — it would raise
    ``TypeError`` and abort the whole diff — and a non-dict row inside the list is skipped,
    matching the fail-soft posture used across the codebase.
    """
    rows = artifact.get("per_repo")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _per_repo_deltas(baseline: dict, candidate: dict) -> list[dict]:
    base_by_key = {_repo_key(row): row for row in _repo_rows(baseline)}
    out = []
    for row in _repo_rows(candidate):
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


def _looks_like_partition(part: dict) -> bool:
    """True when ``part`` resembles ``run_multi_replay()`` partition output."""
    return bool(part) and any(k in part for k in ("scored_repos", "composite_mean", "error"))


def _is_generalization(artifact: dict) -> bool:
    """True only for a ``run_generalization_report`` artifact.

    That report nests per-partition scores under ``tuned`` and ``held_out`` mappings and
    carries no top-level ``composite_mean``. Requiring ``repo_set``, ``generalization_gap``,
    and partition-shaped dicts avoids false positives from unrelated artifacts that happen
    to carry scalar or incomplete ``tuned``/``held_out`` fields.
    """
    if not isinstance(artifact, dict):
        return False
    if "composite_mean" in artifact:
        return False
    if "generalization_gap" not in artifact:
        return False
    if not isinstance(artifact.get("repo_set"), str):
        return False
    tuned = artifact.get("tuned")
    held_out = artifact.get("held_out")
    if not isinstance(tuned, dict) or not isinstance(held_out, dict):
        return False
    return _looks_like_partition(tuned) and _looks_like_partition(held_out)


def _generalization_diff(baseline: dict, candidate: dict) -> dict:
    """Diff the composite means of each partition plus the generalization gap.

    Every value is read through ``_metric_triplet``/``_delta``, which coerce a missing,
    ``None``, or non-numeric field to a ``None`` delta rather than crashing — so a partition
    that only recorded an ``error`` (``scored_repos == 0``) diffs to ``None`` cleanly, and a
    placeholder ``composite_mean`` of ``0.0`` on an unscored partition is treated as
    unavailable (mirroring ``benchmark/trend.py`` and ``benchmark/report.py``).
    """
    out = {}
    for partition in ("tuned", "held_out"):
        base_part = baseline.get(partition)
        cand_part = candidate.get(partition)
        base_part = base_part if isinstance(base_part, dict) else {}
        cand_part = cand_part if isinstance(cand_part, dict) else {}
        out[partition] = {"composite_mean": _metric_triplet(base_part, cand_part, "composite_mean")}
    out["generalization_gap"] = _metric_triplet(baseline, candidate, "generalization_gap")
    return out


def compare_eval_artifacts(baseline: dict, candidate: dict) -> dict:
    """Return a stable JSON summary of how ``candidate`` differs from ``baseline``.

    Standard single/multi-repo artifacts diff their top-level ``composite_mean`` (and any
    optional ``composite_parts``/``judge_report``/``per_repo`` sections). When BOTH artifacts
    are ``run_generalization_report`` shaped — no top-level ``composite_mean``, scores nested
    under ``tuned``/``held_out`` — the top-level ``composite_mean`` triplet is replaced by a
    dedicated ``generalization`` block holding each partition's ``composite_mean`` delta and
    the ``generalization_gap`` delta. The two shapes never share output keys, so an existing
    consumer of standard artifacts is unaffected.
    """
    if _is_generalization(baseline) and _is_generalization(candidate):
        return {"generalization": _generalization_diff(baseline, candidate)}

    parts = {}
    base_parts = _effective_composite_parts(baseline)
    cand_parts = _effective_composite_parts(candidate)
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


def _fmt_delta(triplet: dict) -> str:
    delta = (triplet or {}).get("delta")
    return "n/a" if delta is None else f"{delta:+.3f}"


def comparison_headline(diff: dict) -> str:
    """One-line human summary for stderr."""
    gen = diff.get("generalization")
    if gen:
        return (
            f"compare_eval: tuned {_fmt_delta(gen.get('tuned', {}).get('composite_mean'))} "
            f"held_out {_fmt_delta(gen.get('held_out', {}).get('composite_mean'))} "
            f"gap {_fmt_delta(gen.get('generalization_gap'))}"
        )
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

    try:
        baseline = load_artifact(args.baseline)
        candidate = load_artifact(args.candidate)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    diff = compare_eval_artifacts(baseline, candidate)
    print(comparison_headline(diff), file=sys.stderr)
    print(json.dumps(diff, indent=2))


if __name__ == "__main__":
    main()
