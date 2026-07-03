"""CLI: have the maintainer agent review a live PR and recommend an action.

  python -m scripts.review_pr --repo gittensor-vanguard/vanguarstew --pr 30 \
      --model <m> --api-base <url> --api-key <key>     # live
  VANGUARSTEW_OFFLINE=1 python -m scripts.review_pr --repo <r> --pr <n>   # offline stub

Uses the `gh` CLI to fetch the PR. This is the "maintainer-assist" side of vanguarstew: the
same agent the benchmark scores, applied to a real, current PR.
"""

from __future__ import annotations

import argparse
import json
import subprocess

from agent.llm import LLM
from agent.review import review_pr


def _gh(*args) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True).stdout


def fetch_pr(repo: str, number: int) -> dict:
    data = json.loads(_gh("pr", "view", str(number), "-R", repo, "--json",
                          "number,title,body,author,additions,deletions,files"))
    return {
        "number": data["number"],
        "title": data["title"],
        "body": data.get("body"),
        "author": data["author"]["login"],
        "additions": data["additions"],
        "deletions": data["deletions"],
        "files": [f["path"] for f in data.get("files", [])],
        "diff": _gh("pr", "diff", str(number), "-R", repo),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="maintainer-assist: agent reviews a live PR")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--pr", type=int, required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--api-base", default=None)
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()

    pr = fetch_pr(args.repo, args.pr)
    llm = LLM(model=args.model, api_base=args.api_base, api_key=args.api_key)
    rev = review_pr(pr, None, llm)

    print(f"\n  vanguarstew · maintainer-assist — {args.repo}#{args.pr}")
    print(f"  {pr['title']}  (@{pr['author']}, +{pr['additions']}/-{pr['deletions']})\n")
    print(f"  summary:  {rev.get('summary')}")
    print(f"  scope ok: {rev.get('scope_ok')}    tests present: {rev.get('tests_present')}")
    if rev.get("concerns"):
        print("  concerns:")
        for c in rev["concerns"]:
            print(f"    - {c}")
    print(f"\n  -> action: {rev.get('action')}    value: {rev.get('value_label')}")
    print(f"  -> {rev.get('recommendation')}\n")


if __name__ == "__main__":
    main()
