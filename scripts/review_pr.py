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
import logging
import subprocess

from agent.llm import LLM
from agent.review import review_pr

logger = logging.getLogger(__name__)


def _gh(*args) -> str:
    """Run the ``gh`` CLI and return stdout; raise with gh's stderr on failure.

    ``gh`` exits non-zero with empty stdout and a specific stderr message for bad
    ``--repo``/``--pr``, missing auth, no repo access, rate limits, or network errors.
    Without this check the failure surfaces only as a downstream ``JSONDecodeError``.
    """
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if result.returncode != 0:
        cmd = " ".join(["gh", *args])
        stderr = result.stderr.strip()
        detail = f": {stderr}" if stderr else " (gh produced no error output)"
        raise RuntimeError(f"`{cmd}` failed (exit {result.returncode}){detail}")
    return result.stdout


def _pr_author(data: dict, number: int) -> str:
    """Return the PR author's login, or GitHub's ``ghost`` placeholder when unavailable.

    GitHub returns ``"author": null`` once the author's account no longer exists. A missing
    ``author`` key (not requested / absent from the payload) is treated the same for callers
    but does not emit a warning.
    """
    if "author" not in data:
        return "ghost"
    author = data["author"]
    if author is None:
        logger.warning("review_pr: PR #%s has null author; using 'ghost'", number)
        return "ghost"
    if not isinstance(author, dict):
        logger.warning(
            "review_pr: PR #%s author is %s, not an object; using 'ghost'",
            number,
            type(author).__name__,
        )
        return "ghost"
    login = author.get("login")
    if not isinstance(login, str) or not login.strip():
        logger.warning("review_pr: PR #%s has no author login; using 'ghost'", number)
        return "ghost"
    return login.strip()


def fetch_pr(repo: str, number: int) -> dict:
    data = json.loads(_gh("pr", "view", str(number), "-R", repo, "--json",
                          "number,title,body,author,additions,deletions,files"))
    return {
        "number": data["number"],
        "title": data["title"],
        "body": data.get("body"),
        "author": _pr_author(data, number),
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
