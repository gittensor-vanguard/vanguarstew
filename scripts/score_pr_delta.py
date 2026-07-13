"""CLI: score a PR's ``agent/`` against a baseline on the same benchmark run, and report
which measured-improvement performance band (if any) the PR earns — evidence, not a read
of the diff.

  python -m scripts.score_pr_delta baseline_result.json candidate_result.json

Both inputs are ``run_eval --out`` artifacts (produced by running the SAME repo-set/task
count against the baseline agent and the PR's agent respectively). This tool never runs
the benchmark itself — it only judges two already-produced results — so it has no model,
network, or repo-set opinions of its own.

Policy (the anti-Goodhart floor from docs/spec-driven-development.md / REVIEW.md):
  - A regression on either the judge or the objective component (past the noise floor) is
    a hard merge block for ``agent/`` PRs — trading one axis off for the other (sounding
    better to the judge while the objective anchor quietly drops) counts as a regression,
    not an improvement. This is the Pareto floor. ``band == "blocked"`` / ``blocks_merge``
    reflect this directly.
  - Otherwise, the composite_mean delta is bucketed into a performance band —
    ``perf:xs`` .. ``perf:xl`` — by magnitude (see BAND_THRESHOLDS). A delta at or below
    the noise floor earns ``band == "none"``: still mergeable, just no value multiplier
    (a clean refactor or typo fix with no measurable effect on agent performance).
  - Band thresholds are DELIBERATELY ROUGH right now — this project has one real
    benchmark-delta data point so far. They're a single ordered table
    (BAND_THRESHOLDS) so they can be recalibrated in one place once enough real
    ``score_pr_delta`` runs exist to know what a genuinely large win looks like on this
    benchmark. Log every real result; don't guess twice.
  - This script is a REPORTER, not a gate: it always exits 0. A CI workflow or the
    maintainer bot decides what to do with the recommendation (post a comment, apply a
    label, merge/close) — kept separate so the policy stays testable in isolation from
    that mechanics.
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts.compare_eval import compare_eval_artifacts

DEFAULT_NOISE_FLOOR = 0.01

# Ordered low-to-high performance bands, keyed by the MINIMUM composite_mean delta
# required to reach that band (a delta must clear a band's floor to earn it; the highest
# band whose floor it clears wins). ROUGH / provisional -- see the module docstring.
# perf:none covers 0 < delta <= noise_floor implicitly (handled in score_pr_delta()).
BAND_THRESHOLDS = (
    ("xs", 0.01),
    ("s", 0.02),
    ("m", 0.04),
    ("l", 0.08),
    ("xl", 0.15),
)

# gittensor label_multipliers this repo submits for the perf:* ladder (see REVIEW.md).
# Kept alongside the thresholds so the two never drift apart silently.
BAND_MULTIPLIERS = {
    "xs": 0.5,
    "s": 1.0,
    "m": 1.5,
    "l": 2.5,
    "xl": 4.0,
}


def _delta(triplet: dict | None) -> float | None:
    if not isinstance(triplet, dict):
        return None
    delta = triplet.get("delta")
    return delta if isinstance(delta, (int, float)) else None


def _regressed(delta: float | None, noise_floor: float) -> bool:
    """True only when ``delta`` is a real (past-noise-floor) negative move."""
    return delta is not None and delta < -noise_floor


def _pareto_axes(diff: dict) -> dict:
    """The two components the Pareto floor is measured over: judge_mean, objective_mean.

    Falls back to an empty (unavailable) reading when the artifacts didn't carry
    ``composite_parts`` (e.g. an offline stub run) — an axis that never reported data
    can't be judged to have regressed, so it's excluded from the floor check rather than
    silently treated as a pass or a fail.
    """
    parts = diff.get("composite_parts") or {}
    return {axis: parts.get(axis) for axis in ("judge_mean", "objective_mean")}


def _band_for_delta(delta: float | None, noise_floor: float) -> str:
    """Bucket a composite_mean delta into a performance band. ``None`` or <= the noise
    floor is "none" (no measurable improvement, still mergeable, no multiplier). Otherwise
    the highest BAND_THRESHOLDS entry whose floor the delta clears."""
    if delta is None or delta <= noise_floor:
        return "none"
    band = "none"
    for name, floor in BAND_THRESHOLDS:
        if delta >= floor:
            band = name
    return band


def score_pr_delta(baseline: dict, candidate: dict, noise_floor: float = DEFAULT_NOISE_FLOOR) -> dict:
    """Return the full delta + a performance-band recommendation.

    Handles both the standard (single top-level ``composite_mean``) and the
    generalization-report shape (``tuned``/``held_out`` partitions, no top-level
    ``composite_mean``) — the Pareto floor and banding are checked on whichever composite
    triplet(s) the artifact shape actually produced (generalization uses the MINIMUM of
    the two partitions' deltas, so a PR can't overfit the tuned set and still band high).

    ``band`` is one of:
      - ``"blocked"`` — a scored axis regressed past the noise floor. Hard merge block
        for ``agent/`` PRs (see REVIEW.md).
      - ``"none"``    — no measurable improvement past the noise floor. Still mergeable,
        earns no ``perf:*`` label / multiplier.
      - ``"xs"``..``"xl"`` — a measured composite improvement, bucketed by magnitude per
        BAND_THRESHOLDS. Supports the matching ``perf:*`` label.
    """
    diff = compare_eval_artifacts(baseline, candidate)

    if "generalization" in diff:
        gen = diff["generalization"]
        composite_deltas = {
            part: _delta(gen.get(part, {}).get("composite_mean"))
            for part in ("tuned", "held_out")
        }
        any_regressed = any(_regressed(d, noise_floor) for d in composite_deltas.values())
        present = [d for d in composite_deltas.values() if d is not None]
        banding_delta = min(present) if present else None
        pareto_axes = {}  # no per-axis (judge/objective) split at the generalization level
    else:
        composite_deltas = {"composite_mean": _delta(diff.get("composite_mean"))}
        pareto_axes = _pareto_axes(diff)
        axis_deltas = [_delta(v) for v in pareto_axes.values()]
        any_regressed = any(_regressed(d, noise_floor) for d in axis_deltas)
        banding_delta = composite_deltas["composite_mean"]

    if any_regressed:
        band = "blocked"
        reason = "a scored dimension regressed past the noise floor (Pareto floor)"
    else:
        band = _band_for_delta(banding_delta, noise_floor)
        reason = (
            "no measurable improvement past the noise floor" if band == "none" else
            f"composite_mean improved into the perf:{band} band"
        )

    return {
        "band": band,
        "blocks_merge": band == "blocked",
        "label": None if band in ("blocked", "none") else f"perf:{band}",
        "multiplier": BAND_MULTIPLIERS.get(band),
        "reason": reason,
        "noise_floor": noise_floor,
        "composite_deltas": composite_deltas,
        "pareto_axes": pareto_axes,
        "diff": diff,
    }


def combine_dual_target(public_report: dict, private_report: dict) -> dict:
    """Combine two independent score_pr_delta() reports — one against the public
    curated repo set, one against a private/hidden repo set the PR author never saw —
    into a single conservative verdict: a PR can't earn a band by tuning against the
    repos it can see while flat-lining or regressing on repos it can't.

    Rule: blocked if EITHER report is blocked; otherwise the band is the MINIMUM of the
    two bands (by BAND_THRESHOLDS order, "none" below all bands). This mirrors
    score_pr_delta()'s own generalization-shape handling (min across partitions), just
    applied across two independently-run targets instead of one run's partitions.
    """
    order = ["none"] + [name for name, _ in BAND_THRESHOLDS]

    def _rank(report):
        return -1 if report.get("band") == "blocked" else order.index(report.get("band", "none"))

    if public_report.get("band") == "blocked" or private_report.get("band") == "blocked":
        worse = public_report if public_report.get("band") == "blocked" else private_report
        band = "blocked"
        reason = f"blocked on the {'public' if worse is public_report else 'private'} target: {worse.get('reason', '')}"
    else:
        worse = public_report if _rank(public_report) <= _rank(private_report) else private_report
        band = worse.get("band", "none")
        reason = (
            "combined band is the minimum across public and private targets"
            if band != "none" else
            "no band cleared on both public and private targets"
        )

    return {
        "band": band,
        "blocks_merge": band == "blocked",
        "label": None if band in ("blocked", "none") else f"perf:{band}",
        "multiplier": BAND_MULTIPLIERS.get(band),
        "reason": reason,
        "public": public_report,
        "private": private_report,
    }


def headline(report: dict) -> str:
    band = report.get("band")
    if band == "blocked":
        verdict = "BLOCKED (merge not allowed for agent/ PRs)"
    elif band == "none":
        verdict = "no band (mergeable, no perf:* label)"
    else:
        verdict = f"perf:{band}" if band else "unknown"
    return f"score_pr_delta: {verdict} — {report.get('reason', '')}"


def load_artifact(path: str) -> dict:
    """Load a JSON artifact from ``path``, exiting with a clean error on failure.

    Distinguishes the common ``OSError`` subclasses so the user gets an actionable message
    rather than a raw traceback: ``FileNotFoundError`` (missing), ``PermissionError``
    (unreadable), ``IsADirectoryError`` (a directory, not a file), and any other ``OSError``
    (broken symlink, I/O error, ...). Checks the JSON shape directly rather than delegating
    to a helper that raises a bare ``ValueError`` for it, so nothing here needs -- or risks
    masking bugs behind -- a catch-all ``except ValueError``. Mirrors the pattern already
    established in ``scripts/repo_task_mean.py`` and the other CLIs hardened this way (#1376).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"artifact not found: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except PermissionError:
        print(f"artifact is not readable (check file permissions): {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except IsADirectoryError:
        print(f"artifact path is a directory, not a file: {path}", file=sys.stderr)
        raise SystemExit(2) from None
    except OSError as exc:
        print(f"cannot read artifact ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except ValueError as exc:
        # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal
        # beyond the int-string-conversion limit (py3.11+); JSONDecodeError subclasses it.
        print(f"artifact is not valid JSON ({path}): {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    if not isinstance(data, dict):
        print(f"artifact must be a JSON object: {path}", file=sys.stderr)
        raise SystemExit(2)
    return data


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("baseline", help="run_eval --out artifact for the baseline agent")
    ap.add_argument("candidate", help="run_eval --out artifact for the PR's agent")
    ap.add_argument("--noise-floor", type=float, default=DEFAULT_NOISE_FLOOR,
                    help="minimum |delta| to count as a real change (default 0.01)")
    ap.add_argument("--out", default=None, help="write the full JSON report to this path")
    args = ap.parse_args(argv)

    try:
        baseline = load_artifact(args.baseline)
        candidate = load_artifact(args.candidate)
    except SystemExit as exc:
        return int(exc.code)

    report = score_pr_delta(baseline, candidate, noise_floor=args.noise_floor)

    print(headline(report), file=sys.stderr)
    text = json.dumps(report, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        print(text)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
