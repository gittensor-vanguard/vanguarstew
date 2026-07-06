"""Leakage defenses applied to the frozen-at-T context.

Even data that is legitimately knowable at T can *cross-reference* the future — a commit
subject like "part of #512", a `Fixes #900` backlink, a link to a later PR, or a raw commit
SHA. Those leak where the repo went next. We neutralize such references in the free-text
fields of the context while keeping the substantive content (the roadmap, titles, prose)
the agent legitimately needs to infer trajectory.

This is deterministic and offline; it is one layer of the leakage strategy (see
docs/architecture.md), alongside the no-internet sandbox and recent/obscure repo selection.

The GitHub-link matcher is boundary-aware: it stops at the structural characters
that surround a URL in prose or markdown (parens, square/angle brackets, quotes)
and peels trailing sentence punctuation (.,;!) back into the surrounding text, so
legitimate context survives while the forward reference itself is masked. Bare
owner/repo URLs (which carry no specific forward reference) are left untouched.
"""

from __future__ import annotations

import re

# Characters that surround a URL in prose or markdown and are never part of it.
# Stopping at them keeps the surrounding syntax — parentheses, square/angle
# brackets, quotes — intact instead of swallowing it into the mask.
_URL_STOP = "<>()[]{}\"'`"

# A GitHub deep-link whose target references the repo's future state: a later issue/PR/commit,
# a *future release tag* (``releases/tag/vX`` hands over the next version outright and defeats
# the release/bump scoring in score.py), or a tree/blob/compare at a future ref, plus milestone
# and discussion pages that point at where the repo is heading. The owner/repo and trailing
# id/path segments are bounded by ``_URL_STOP`` so the matcher never runs past a closing
# delimiter, and the recognized link *types* live in a single readable alternation. The bare
# repo/owner URL (no item path, e.g. github.com/owner/repo) is deliberately left intact so
# legitimate references survive.
_GH_LINK = re.compile(
    r"https?://(?:www\.)?github\.com"                        # github.com or www.github.com
    r"/[^\s" + re.escape(_URL_STOP) + r"]+/"                  # owner/repo/
    r"(?:issues|pull|pulls|commit|commits|compare|releases|tag|tags|tree|blob|"
    r"milestone|milestones|discussions)/"           # a forward-referencing link type
    r"[^\s" + re.escape(_URL_STOP) + r"]+",                    # referenced id / path
    re.I,
)

# Trailing sentence punctuation the greedy id/path segment may swallow; we peel
# it back off so a trailing ".", ",", ";", or "!" stays in the surrounding prose
# rather than vanishing into <link>. Query ("?") / fragment ("#") separators are
# NOT here — they are legitimate URL characters and must remain masked.
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
    """True when a free-text token should be treated as a raw commit SHA.

    Bare numeric tokens are intentionally preserved. They are technically valid hex, but in
    prose they are far more likely to be counts, years, IDs, or measurements; masking them
    destroys useful benchmark content. Requiring at least one hex letter keeps realistic SHAs
    scrubbed while avoiding broad numeric false positives.
    """
    low = (token or "").lower()
    return bool(_SHA.fullmatch(low) and any(c in "abcdef" for c in low))


def strip_forward_refs(text: str) -> str:
    """Mask issue/PR back-references, GitHub links, and raw SHAs in free text."""
    if not isinstance(text, str):
        return ""
    if not text:
        return text
    text = _GH_LINK.sub(_mask_link, text)
    text = _ISSUE_REF.sub("#ref", text)
    text = _SHA.sub(lambda m: "<sha>" if _looks_like_sha(m.group(0)) else m.group(0), text)
    return text


def _scrub_list(items) -> list:
    """Return ``items`` when it is a list; otherwise treat as no entries.

    A truthy non-list (``42``, ``True``, a bare dict) must not reach ``for item in items``
    or malformed frozen context aborts leakage scrubbing (#467).
    """
    return items if isinstance(items, list) else []


def _scrub_titles(items, key):
    out = []
    for item in _scrub_list(items):
        if isinstance(item, dict):
            item = dict(item)
            if key in item:
                item[key] = strip_forward_refs(item.get(key, ""))
            out.append(item)
        else:
            out.append(item)
    return out


def scrub_context(context: dict) -> dict:
    """Return a copy of the context with forward-looking references neutralized."""
    ctx = dict(context)
    ctx["readme_excerpt"] = strip_forward_refs(ctx.get("readme_excerpt", ""))
    ctx["recent_commits"] = _scrub_titles(ctx.get("recent_commits"), "subject")
    ctx["open_issues"] = _scrub_titles(ctx.get("open_issues"), "title")
    ctx["open_prs"] = _scrub_titles(ctx.get("open_prs"), "title")
    ctx["milestones"] = _scrub_titles(ctx.get("milestones"), "title")
    # Scrub both keys: the GitHub-API path carries `name`, but the default git-freeze path
    # emits `{"tag": t}` with no `name`, so the tag is a release's only identifier there.
    ctx["releases"] = _scrub_titles(_scrub_titles(ctx.get("releases"), "tag"), "name")
    ctx["_forward_signal_scrubbed"] = True
    return ctx
