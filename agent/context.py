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

# README filenames probed by git-only context builders, in priority order. ``benchmark/freeze.py``
# imports this tuple so freeze and agent fallback stay aligned (#749 tag filtering already does).
README_PROBE_NAMES = ("README.md", "README.rst", "README.txt", "README", "docs/README.md")

# Issue/PR back-reference (`#123`), GitHub deep-links, and raw commit SHAs. The scored replay
# path masks all three via ``benchmark.leakage.strip_forward_refs`` before the agent sees the
# text; this module's git-only fallback must mirror that policy locally. We deliberately do NOT
# import from ``benchmark/`` (``agent/`` must not depend on it — a miner-only split is planned).
# Keep this logic aligned with ``benchmark/leakage.py`` and ``docs/architecture.md``.
_URL_STOP = "<>()[]{}\"'`"

_GH_LINK = re.compile(
    # The scheme is optional: GitHub and markdown auto-link a scheme-less `github.com/...`, so a
    # deep-link written without `https://` (common in commit subjects and READMEs) is just as much a
    # forward-reference and must be masked (mirrors benchmark/leakage.py, fixed in #946). The
    # `(?<![\w.])` boundary keeps a look-alike host (`notgithub.com`, `foo.github.com`) from matching.
    r"(?<![\w.])(?:https?://)?(?:www\.)?github\.com"
    r"/[^\s" + re.escape(_URL_STOP) + r"]+/"
    r"(?:issues|pull|pulls|commit|commits|compare|releases|tag|tags|tree|blob|"
    r"milestone|milestones|discussions)/"
    r"[^\s" + re.escape(_URL_STOP) + r"]+",
    re.I,
)

_TRAILING_PUNCT = ".,;!"

_ISSUE_REF = re.compile(r"#\d+")
# Raw commit hashes: a word-bounded hex run of 7-40 chars (abbreviated or full SHA-1) or
# exactly 64 chars (a full SHA-256 object hash; git has supported the SHA-256 format since
# 2.29). The exact-64 arm is separate so lengths 41-63 stay unmasked, keeping the guard off
# arbitrary long hex-like tokens that are not real hashes. The 64-char arm also requires at
# least one hex letter in the pattern so all-numeric 64-char prose (counts, IDs) never even
# enters the SHA candidate set. Shorter runs still rely on ``_looks_like_sha`` for the same
# numeric-preservation policy. Keep aligned with ``benchmark/leakage.py``.
_SHA = re.compile(
    r"\b(?:"
    r"[0-9a-f]{7,40}|"
    r"(?=[0-9a-f]{64}\b)(?=[0-9a-f]*[a-f])[0-9a-f]{64}"
    r")\b",
    re.I,
)


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
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            # A present-but-unreadable context file must not abort solve(): fall back to
            # rebuilding the knowable-at-T context from the frozen git checkout (leakage-safe —
            # the checkout is frozen at T), exactly as when the file is absent. This is the
            # repo's "degrade rather than crash on malformed frozen input" posture (spec 001).
            #
            # Catch only the specific failure modes, never a bare Exception:
            #   - json.JSONDecodeError: truncated/partial write from an interrupted freeze;
            #   - UnicodeDecodeError:   non-UTF-8 / binary content;
            #   - OSError (incl. PermissionError, IsADirectoryError): the file cannot be read.
            # The git rebuild cannot recover the GitHub-derived issues/PRs/labels a partial file
            # may have held, so log loudly (with the byte size) — the degrade is never silent.
            try:
                size = os.path.getsize(path)
            except OSError:
                size = -1
            logger.warning(
                "load_context: %s unreadable (%s bytes, %s: %s); rebuilding from git",
                path, size, type(exc).__name__, exc,
            )
    return _context_from_git(repo_path)


def _agent_context_list(items, field: str) -> list:
    """Return ``items`` when it is a list; otherwise treat as empty.

    A truthy non-list must not reach ``for item in items`` or malformed frozen context
    aborts the agent prompt path (#493). An empty list is returned so the caller still
    surfaces list-shaped keys with ``[]`` rather than omitting them.
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


# Backward-compatible alias for callers/tests that still import the old name.
_agent_issue_pr_list = _agent_context_list


def context_for_agent(context: dict) -> dict:
    """Return the agent-facing view of frozen context.

    Issue/PR labels are historical only when ``labels_as_of_t`` is explicitly true. When the
    flag is false or missing we omit ``labels`` from the agent-facing prompt view, so ``[]`` is
    not misread as "this item had no labels at T" when the real meaning is "label history
    unavailable".

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
        for idx, item in enumerate(_agent_context_list(out.get(key), key)):
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
            if clean.get("labels_as_of_t") is not True:
                clean.pop("labels", None)
            items.append(clean)
        out[key] = items
    for key in ("recent_commits", "releases", "milestones", "labels"):
        out[key] = _agent_context_list(out.get(key), key)
    if out.get("_issues_truncated") is True:
        # Defense in depth for older frozen artifacts that still carry a partial backlog.
        out["open_issues"] = []
        out["open_prs"] = []
    if out.get("_milestones_truncated") is True:
        out["milestones"] = []
    if out.get("_releases_truncated") is True:
        out["releases"] = []
    return out


def _context_from_git(repo_path: str) -> dict:
    head = _git(repo_path, "rev-parse", "HEAD")
    freeze_date = _git(repo_path, "show", "-s", "--format=%cI", head).strip() or None
    log = _git(repo_path, "log", "--pretty=format:%H%x09%s", "-n", "50")
    commits = []
    for line in log.splitlines():
        if "\t" in line:
            h, subj = line.split("\t", 1)
            commits.append({"sha": h[:10], "subject": _mask_forward_refs(subj)})
    # `git tag --merged` selects tags whose target commit is reachable from T; it does NOT
    # filter by when the tag was created. An annotated tag cut after T from a commit already
    # present at T would leak a future release into knowable-at-T context. Filter to tags
    # whose creator date is <= T, matching `benchmark/freeze.py::build_context` (#749).
    frozen_ts = _git(repo_path, "show", "-s", "--format=%ct", head).strip()
    frozen_at = int(frozen_ts) if frozen_ts.isdigit() else None
    tags = []
    raw_tags = _git(
        repo_path, "tag", "--merged", head, "--sort=creatordate",
        "--format=%(creatordate:unix)%09%(refname:strip=2)",
    )
    for line in raw_tags.splitlines():
        ts, _, name = line.partition("\t")
        if not name:
            continue
        if frozen_at is not None and ts.isdigit() and int(ts) > frozen_at:
            continue
        tags.append(name)
    readme = ""
    for name in README_PROBE_NAMES:
        p = os.path.join(repo_path, name)
        if not os.path.isfile(p):
            continue
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        # An empty higher-priority README must not shadow a populated lower-priority one: skip
        # it and keep probing, mirroring build_context's truthy ``if content`` check (freeze
        # reads a missing *and* an empty file as an empty string alike). Otherwise the two
        # git-only context builders diverge on the same repo -- freeze surfaces the lower
        # README while this fallback stops at the empty one -- so philosophy/plan prompts and
        # scoring inputs differ by code path (the #916/#937 alignment invariant).
        if content:
            readme = _mask_forward_refs(content[:4000])
            break
    return {
        "frozen_at": {"commit": head[:10], "date": freeze_date},
        "recent_commits": commits,
        "open_issues": [],
        "open_prs": [],
        "labels": [],
        "milestones": [],
        "releases": [{"tag": _mask_forward_refs(t)} for t in tags[-10:]],
        "readme_excerpt": readme,
        "_source": "git",
    }
