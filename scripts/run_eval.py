"""CLI: run an end-to-end time-travel replay eval.

  VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repo /path/to/git/repo --tasks 2 --horizon 5
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from benchmark.baselines import BASELINES, DEFAULT_BASELINE
from benchmark.runner import (
    run_generalization_report,
    run_multi_replay,
    run_replay,
    weight_sweep,
)

logger = logging.getLogger(__name__)


def write_result_artifact(path: str, result: dict) -> None:
    """Persist a replay result as JSON for later comparison/trending."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
        f.write("\n")


def result_summary_lines(result: dict) -> list[str]:
    """Short human-readable lines for stderr reporting.

    Keep stdout as JSON so callers can pipe or store the full artifact unchanged.
    """
    report = result.get("judge_report")
    if isinstance(report, dict) and report.get("summary"):
        return [report["summary"]]
    return []


def _numeric_score(value) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def check_score_floor(result: dict, fail_under: float | None) -> str | None:
    """Return an error message when ``composite_mean`` is below ``fail_under``, else None."""
    if fail_under is None:
        return None
    # Generalization reports nest composite_mean under tuned/held_out — no top-level field.
    if "tuned" in result and "held_out" in result:
        for label in ("tuned", "held_out"):
            part = result.get(label) or {}
            if not part.get("scored_repos"):
                continue
            score = _numeric_score(part.get("composite_mean"))
            if score is None:
                return (f"score floor {fail_under}: {label} composite_mean "
                        "missing or non-numeric")
            if score < fail_under:
                return (f"score floor {fail_under}: {label} composite_mean "
                        f"{score:.3f} below threshold")
        return None
    score = _numeric_score(result.get("composite_mean"))
    if score is None:
        return f"score floor {fail_under}: composite_mean missing or non-numeric"
    if score < fail_under:
        return f"score floor {fail_under}: composite_mean {score:.3f} below threshold"
    return None


def _weight_sweep_rows(result: dict) -> list:
    """Return ``weight_sweep`` rows when list-shaped; otherwise treat as no sweep output.

    A truthy non-list in a loaded or malformed result must not abort stderr reporting
    (#573).
    """
    rows = result.get("weight_sweep")
    if isinstance(rows, list):
        return rows
    if rows is not None:
        logger.warning(
            "run_eval: weight_sweep is %s, not a list; skipping stderr sweep output",
            type(rows).__name__,
        )
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description="vanguarstew time-travel replay eval")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", help="path to a single local git repo to replay")
    src.add_argument("--repos", nargs="+",
                     help="two or more git repos to replay and aggregate into a composite_mean")
    src.add_argument("--repo-set",
                     help="validated repo-set JSON config to replay (see benchmark/repo_sets/)")
    ap.add_argument("--repo-set-partition", default="tuned",
                    choices=["tuned", "held_out", "all"],
                    help="which repos from --repo-set to replay (default: tuned)")
    ap.add_argument("--agent", default="agent.py", help="agent entrypoint file")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, choices=sorted(BASELINES),
                    help="reference opponent the challenger is judged against")
    ap.add_argument("--tasks", type=int, default=3)
    ap.add_argument("--horizon", type=int, default=5, help="next-N maintainer actions to predict")
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-base", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--work-dir", default=None, help="keep frozen checkouts here (else temp)")
    ap.add_argument("--out", default=None, help="write the full JSON result artifact to this path")
    ap.add_argument("--fail-under", type=float, default=None,
                    help="exit with status 1 when composite_mean is below this floor")
    ap.add_argument("--enrich", action="store_true",
                    help="enrich frozen context with GitHub issues/PRs/releases knowable at T")
    ap.add_argument("--github-token", default=None, help="GitHub token (else $GITHUB_TOKEN)")
    ap.add_argument("--recent-bias", action="store_true",
                    help="draw freeze points only from the most recent usable window")
    ap.add_argument("--rotation-seed", type=int, default=None,
                    help="deterministically rotate which freeze points are chosen")
    ap.add_argument("--w-judge", type=float, default=0.6,
                    help="composite weight on the pairwise judge (default 0.6)")
    ap.add_argument("--w-objective", type=float, default=0.4,
                    help="composite weight on the objective anchor (default 0.4)")
    ap.add_argument("--single-order-judge", action="store_true",
                    help="ask the judge one randomized order instead of both "
                         "(cheaper, but no position-swap consistency check)")
    ap.add_argument("--held-out", action="store_true",
                    help="with --repo-set, replay the held-out slice instead of tuned repos")
    ap.add_argument("--generalization", action="store_true",
                    help="with --repo-set, replay BOTH the tuned and held-out partitions and "
                         "report the generalization gap (tuned minus held-out composite mean)")
    ap.add_argument("--sweep-weights", action="store_true",
                    help="after a single-repo replay, re-blend the same tasks over a small "
                         "judge/objective weight grid and print (weights -> composite_mean); "
                         "helps tune --w-judge/--w-objective without re-running the replay")
    args = ap.parse_args()
    if args.held_out and not args.repo_set:
        ap.error("--held-out requires --repo-set")
    if args.generalization and not args.repo_set:
        ap.error("--generalization requires --repo-set")
    if args.generalization and args.held_out:
        ap.error("--generalization already runs both partitions; do not combine it with --held-out")

    common = dict(
        agent_file=args.agent, n_tasks=args.tasks, horizon=args.horizon,
        model=args.model, api_base=args.api_base, api_key=args.api_key, work_dir=args.work_dir,
        enrich_github=args.enrich, github_token=args.github_token,
        recent_bias=args.recent_bias, rotation_seed=args.rotation_seed, baseline=args.baseline,
        w_judge=args.w_judge, w_objective=args.w_objective,
        dual_order_judge=not args.single_order_judge,
    )
    if args.repo_set and args.generalization:
        result = run_generalization_report(args.repo_set, **common)
    elif args.repo_set:
        partition = "held_out" if args.held_out and args.repo_set_partition == "tuned" else args.repo_set_partition
        result = run_multi_replay(repo_set=args.repo_set, repo_set_partition=partition, **common)
    elif args.repos:
        result = run_multi_replay(args.repos, **common)
    else:
        result = run_replay(repo_path=args.repo, **common)
    if args.sweep_weights:
        rows = result.get("rows")
        if rows:
            result["weight_sweep"] = weight_sweep(rows)
        else:
            print("--sweep-weights needs a single-repo run (--repo); no per-task rows to sweep",
                  file=sys.stderr)
    if args.out:
        write_result_artifact(args.out, result)
    for line in result_summary_lines(result):
        print(line, file=sys.stderr)
    for row in _weight_sweep_rows(result):
        print(f"  weights judge={row['w_judge']} objective={row['w_objective']} "
              f"-> composite_mean={row['composite_mean']}", file=sys.stderr)
    print(json.dumps(result, indent=2))
    floor_err = check_score_floor(result, args.fail_under)
    if floor_err:
        print(floor_err, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
