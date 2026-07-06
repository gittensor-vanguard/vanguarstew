"""Load the frozen, knowable-at-T repository context that the agent reasons over.

The benchmark freezes a repo at commit T and writes `.vanguarstew_context.json` into the
checkout (the GitHub-derived state: issues, PRs, releases, etc. — only what was knowable
at T). If that file is absent, we fall back to what git alone can tell us (commits up to
T, tags as releases, the README). The agent must never look past T.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

CONTEXT_FILE = ".vanguarstew_context.json"

# Issue/PR back-reference (`#123`), GitHub deep-links, and raw commit SHAs. The scored replay
# path masks all three via ``benchmark.leakage.strip_forward_refs`` before the agent sees the
# text; this module's git-only fallback must mirror that policy locally. We deliberately do NOT
# import from ``benchmark/`` (``agent/`` must not depend on it — a miner-only split is planned).
# Keep this logic aligned with ``benchmark/leakage.py`` and ``docs/architecture.md``.
_URL_STOP = "<>()[]{}\"'`"

_GH_LINK = re.compile(
    r"https?://(?:www\.)?github\.com"
    r"/[^\s" + re.escape(_URL_STOP) + r"]+/"
    r"(?:issues|pull|pulls|commit|commits|compare|releases|tag|tags|tree|blob|"
    r"milestone|milestones|discussions)/"
    r"[^\s" + re.escape(_URL_STOP) + r"]+",
    re.I,
)

_TRAILING_PUNCT = ".,;!"

_ISSUE_REF = re.compile(r"#\d+")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


def _mask_link(match) -> str:
    """Replace a GitHub deep-link with ``<link>``, preserving trailing punctuation."""
    url = match.group(0)
    cut = len(url)
    while cut > 0 and url[cut - 1] in _TRAILING_PUNCT:
        cut -= 1
    return "<link>" + url[cut:]


def _looks_like_sha(token: str) -> bool:
    low = (token or "").lower()
    return bool(_SHA.fullmatch(low) and any(c in "abcdef" for c in low))


def _mask_forward_refs(text: str) -> str:
    """Mask issue/PR back-references, GitHub deep-links, and raw SHAs in free text.

    A README or commit subject like "see #150 for the roadmap" or a link to a later PR would
    otherwise leak where the repo went next, violating the knowable-at-T contract this module's
    fallback must honor. Non-string inputs are treated as empty scrubbable text, matching the
    fail-soft posture of ``benchmark.leakage.strip_forward_refs`` without importing from
    ``benchmark/``.
    """
    if not isinstance(text, str):
        return ""
    if not text:
        return text
    text = _GH_LINK.sub(_mask_link, text)
    text = _ISSUE_REF.sub("#ref", text)
    text = _SHA.sub(lambda m: "<sha>" if _looks_like_sha(m.group(0)) else m.group(0), text)
    return text


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


def _agent_issue_pr_list(items, field: str) -> list:
    """Return ``items`` when it is a list; otherwise treat as no issues/PRs.

    A truthy non-list must not reach ``for item in items`` or malformed frozen context
    aborts the agent prompt path (#493). An empty list is returned so the caller still
    surfaces ``open_issues`` / ``open_prs`` keys with ``[]`` rather than omitting them.
    """
    if isinstance(items, list):
        return items
    if items is not None:
        logger.warning(
            "context_for_agent: %s is %s, not a list; treating as empty",
            field,
            type(items).__name__,
        )
    return []


def context_for_agent(context: dict) -> dict:
    """Return the agent-facing view of frozen context.

    Issue/PR labels are historical only when ``labels_as_of_t`` is true. When that flag is
    false we omit ``labels`` from the agent-facing prompt view, so ``[]`` is not misread as
    "this item had no labels at T" when the real meaning is "label history unavailable".

    A non-dict ``context`` is treated as empty (``{}``), matching the fail-closed posture
    used when frozen context is unavailable.
    """
    if not isinstance(context, dict):
        logger.warning(
            "context_for_agent: context is %s, not a dict; treating as empty",
            type(context).__name__ if context is not None else "None",
        )
        return {}
    out = dict(context)
    for key in ("open_issues", "open_prs"):
        items = []
        for idx, item in enumerate(_agent_issue_pr_list(out.get(key), key)):
            if not isinstance(item, dict):
                logger.warning(
                    "context_for_agent: non-dict %s entry at index %d (%s: %r); passing through",
                    key,
                    idx,
                    type(item).__name__,
                    item,
                )
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
            commits.append({"sha": h[:10], "subject": _mask_forward_refs(subj)})
    # `--merged head` restricts to tags reachable from T -- without it, a tag that only
    # exists on an unmerged branch (or otherwise isn't an ancestor of T) would leak into
    # "releases" even though it was never knowable at T. Mirrors the same reachability
    # guard `benchmark/freeze.py::build_context` applies for the harness-driven path.
    tags = [
        t for t in _git(repo_path, "tag", "--sort=-creatordate", "--merged", head).splitlines()
        if t
    ]
    readme = ""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = os.path.join(repo_path, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                readme = _mask_forward_refs(f.read()[:4000])
            break
    return {
        "frozen_at": {"commit": head[:10]},
        "recent_commits": commits,
        "open_issues": [],
        "open_prs": [],
        "labels": [],
        "milestones": [],
        "releases": [{"tag": _mask_forward_refs(t)} for t in tags[:10]],
        "readme_excerpt": readme,
        "_source": "git",
    }
