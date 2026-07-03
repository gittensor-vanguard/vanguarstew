"""CLI: run an end-to-end time-travel replay eval.

  VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repo /path/to/git/repo --tasks 2 --horizon 5
"""

from __future__ import annotations

import argparse
import json

from benchmark.baselines import BASELINES, DEFAULT_BASELINE
from benchmark.runner import run_multi_replay, run_replay


def main() -> None:
    ap = argparse.ArgumentParser(description="vanguarstew time-travel replay eval")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", help="path to a single local git repo to replay")
    src.add_argument("--repos", nargs="+",
                     help="two or more git repos to replay and aggregate into a composite_mean")
    ap.add_argument("--agent", default="agent.py", help="agent entrypoint file")
    ap.add_argument("--baseline", default=DEFAULT_BASELINE, choices=sorted(BASELINES),
                    help="reference opponent the challenger is judged against")
    ap.add_argument("--tasks", type=int, default=3)
    ap.add_argument("--horizon", type=int, default=5, help="next-N maintainer actions to predict")
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-base", default=None)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--work-dir", default=None, help="keep frozen checkouts here (else temp)")
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
    args = ap.parse_args()

    common = dict(
        agent_file=args.agent, n_tasks=args.tasks, horizon=args.horizon,
        model=args.model, api_base=args.api_base, api_key=args.api_key, work_dir=args.work_dir,
        enrich_github=args.enrich, github_token=args.github_token,
        recent_bias=args.recent_bias, rotation_seed=args.rotation_seed, baseline=args.baseline,
        w_judge=args.w_judge, w_objective=args.w_objective,
    )
    if args.repos:
        result = run_multi_replay(args.repos, **common)
    else:
        result = run_replay(repo_path=args.repo, **common)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
