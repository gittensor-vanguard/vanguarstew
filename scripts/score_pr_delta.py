"""CLI: score a PR's ``agent/`` against a baseline on the same benchmark run, and report
whether the measured delta supports a high-value ``mult:*`` label — evidence, not a read
of the diff.

  python -m scripts.score_pr_delta baseline_result.json candidate_result.json

Both inputs are ``run_eval --out`` artifacts (produced by running the SAME repo-set/task
count against the baseline agent and the PR's agent respectively). This tool never runs
the benchmark itself — it only judges two already-produced results — so it has no model,
network, or repo-set opinions of its own.

Policy (the anti-Goodhart floor from docs/spec-driven-development.md / REVIEW.md):
  - A PR is eligible for a top-value label ONLY when composite_mean measurably improved
    AND neither the judge nor the objective component regressed. Improving one axis by
    quietly trading off the other does not count — this is the Pareto floor.
  - "Improved"/"regressed" are judged past a small noise tolerance (``--noise-floor``,
    default 0.01) so a run-to-run wobble from LLM sampling isn't mistaken for a real
    change in either direction.
  - This script is a REPORTER, not a gate: it always exits 0. A CI workflow decides what
    to do with the recommendation (post a comment, cap a label, etc.) — kept separate so
    the policy stays testable in isolation from CI mechanics.
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.compare_eval import compare_eval_artifacts, load_artifact

DEFAULT_NOISE_FLOOR = 0.01


def _delta(triplet: dict | None) -> float | None:
    if not isinstance(triplet, dict):
        return None
    delta = triplet.get("delta")
    return delta if isinstance(delta, (int, float)) else None


def _regressed(delta: float | None, noise_floor: float) -> bool:
    """True only when ``delta`` is a real (past-noise-floor) negative move."""
    return delta is not None and delta < -noise_floor


def _improved(delta: float | None, noise_floor: float) -> bool:
    """True only when ``delta`` is a real (past-noise-floor) positive move."""
    return delta is not None and delta > noise_floor


def _pareto_axes(diff: dict) -> dict:
    """The two components the Pareto floor is measured over: judge_mean, objective_mean.

    Falls back to an empty (unavailable) reading when the artifacts didn't carry
    ``composite_parts`` (e.g. an offline stub run) — an axis that never reported data
    can't be judged to have regressed, so it's excluded from the floor check rather than
    silently treated as a pass or a fail.
    """
    parts = diff.get("composite_parts") or {}
    return {axis: parts.get(axis) for axis in ("judge_mean", "objective_mean")}


def score_pr_delta(baseline: dict, candidate: dict, noise_floor: float = DEFAULT_NOISE_FLOOR) -> dict:
    """Return the full delta + a tier-eligibility recommendation.

    Handles both the standard (single top-level ``composite_mean``) and the
    generalization-report shape (``tuned``/``held_out`` partitions, no top-level
    ``composite_mean``) — the Pareto floor is checked on whichever composite triplet(s)
    the artifact shape actually produced.
    """
    diff = compare_eval_artifacts(baseline, candidate)

    if "generalization" in diff:
        gen = diff["generalization"]
        composite_deltas = {
            part: _delta(gen.get(part, {}).get("composite_mean"))
            for part in ("tuned", "held_out")
        }
        any_regressed = any(_regressed(d, noise_floor) for d in composite_deltas.values())
        any_improved = any(_improved(d, noise_floor) for d in composite_deltas.values())
        pareto_axes = {}  # no per-axis (judge/objective) split at the generalization level
    else:
        composite_deltas = {"composite_mean": _delta(diff.get("composite_mean"))}
        pareto_axes = _pareto_axes(diff)
        axis_deltas = [_delta(v) for v in pareto_axes.values()]
        any_regressed = any(_regressed(d, noise_floor) for d in axis_deltas)
        any_improved = _improved(composite_deltas["composite_mean"], noise_floor)

    if any_regressed:
        eligible, reason = False, "a scored dimension regressed past the noise floor (Pareto floor)"
    elif any_improved:
        eligible, reason = True, "composite_mean improved with no dimension regression"
    else:
        eligible, reason = False, "no measurable improvement past the noise floor"

    return {
        "eligible_for_high_tier": eligible,
        "reason": reason,
        "noise_floor": noise_floor,
        "composite_deltas": composite_deltas,
        "pareto_axes": pareto_axes,
        "diff": diff,
    }


def headline(report: dict) -> str:
    verdict = "ELIGIBLE" if report.get("eligible_for_high_tier") else "not eligible"
    return f"score_pr_delta: {verdict} for a high-value label — {report.get('reason', '')}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", help="run_eval --out artifact for the baseline agent")
    ap.add_argument("candidate", help="run_eval --out artifact for the PR's agent")
    ap.add_argument("--noise-floor", type=float, default=DEFAULT_NOISE_FLOOR,
                    help="minimum |delta| to count as a real change (default 0.01)")
    ap.add_argument("--out", default=None, help="write the full JSON report to this path")
    args = ap.parse_args(argv)

    baseline = load_artifact(args.baseline)
    candidate = load_artifact(args.candidate)
    report = score_pr_delta(baseline, candidate, noise_floor=args.noise_floor)

    print(headline(report), file=sys.stderr)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
