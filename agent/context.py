"""Load the frozen, knowable-at-T repository context that the agent reasons over.

The benchmark freezes a repo at commit T and writes `.vanguarstew_context.json` into the
checkout (the GitHub-derived state: issues, PRs, releases, etc. — only what was knowable
at T). If that file is absent, we fall back to what git alone can tell us (commits up to
T, tags as releases, the README). The agent must never look past T.
"""

from __future__ import annotations

import json
import os
import subprocess

CONTEXT_FILE = ".vanguarstew_context.json"
PROMPT_CONTEXT_KEYS = (
    "frozen_at", "recent_commits", "open_issues", "open_prs",
    "labels", "milestones", "releases", "readme_excerpt",
)


def _git(repo_path, *args):
    out = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def load_context(repo_path: str) -> dict:
    path = os.path.join(repo_path, CONTEXT_FILE)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return _context_from_git(repo_path)


def prompt_context(context: dict) -> dict:
    """Context projection for LLM prompts.

    Issue/PR label history is only historically exact when `labels_as_of_t` is true.
    When reconstruction was unavailable, the frozen context stores `labels: []` as a
    fail-closed sentinel; prompt consumers must not present that as "no labels at T".
    This view normalizes those entries to `labels: null` while preserving the explicit
    `labels_as_of_t: false` marker.
    """
    keep = {k: context.get(k) for k in PROMPT_CONTEXT_KEYS}
    keep["open_issues"] = _prompt_issue_pr_items(keep.get("open_issues"))
    keep["open_prs"] = _prompt_issue_pr_items(keep.get("open_prs"))
    return keep


def _prompt_issue_pr_items(items):
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            out.append(item)
            continue
        rec = dict(item)
        if rec.get("labels_as_of_t") is False:
            rec["labels"] = None
        out.append(rec)
    return out


def _context_from_git(repo_path: str) -> dict:
    head = _git(repo_path, "rev-parse", "HEAD")
    log = _git(repo_path, "log", "--pretty=format:%H%x09%s", "-n", "50")
    commits = []
    for line in log.splitlines():
        if "\t" in line:
            h, subj = line.split("\t", 1)
            commits.append({"sha": h[:10], "subject": subj})
    tags = [t for t in _git(repo_path, "tag", "--sort=-creatordate").splitlines() if t]
    readme = ""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = os.path.join(repo_path, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                readme = f.read()[:4000]
            break
    return {
        "frozen_at": {"commit": head[:10]},
        "recent_commits": commits,
        "open_issues": [],
        "open_prs": [],
        "labels": [],
        "milestones": [],
        "releases": [{"tag": t} for t in tags[:10]],
        "readme_excerpt": readme,
        "_source": "git",
    }
