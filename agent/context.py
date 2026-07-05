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


def context_for_agent(context: dict) -> dict:
    """Return the agent-facing view of frozen context.

    Issue/PR labels are historical only when ``labels_as_of_t`` is true. When that flag is
    false we omit ``labels`` from the agent-facing prompt view, so ``[]`` is not misread as
    "this item had no labels at T" when the real meaning is "label history unavailable".
    """
    out = dict(context or {})
    for key in ("open_issues", "open_prs"):
        items = []
        for item in out.get(key) or []:
            if not isinstance(item, dict):
                items.append(item)
                continue
            clean = dict(item)
            if clean.get("labels_as_of_t") is False:
                clean.pop("labels", None)
            items.append(clean)
        out[key] = items
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
