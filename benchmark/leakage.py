"""Leakage defenses applied to the frozen-at-T context.

Even data that is legitimately knowable at T can *cross-reference* the future — a commit
subject like "part of #512", a `Fixes #900` backlink, a link to a later PR, or a raw commit
SHA. Those leak where the repo went next. We neutralize such references in the free-text
fields of the context while keeping the substantive content (the roadmap, titles, prose)
the agent legitimately needs to infer trajectory.

This is deterministic and offline; it is one layer of the leakage strategy (see
docs/architecture.md), alongside the no-internet sandbox and recent/obscure repo selection.
"""

from __future__ import annotations

import re

_GH_LINK = re.compile(
    r"https?://github\.com/[^\s)]+/(?:issues|pull|commit|compare)/[^\s)]+", re.I)
_ISSUE_REF = re.compile(r"#\d+")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)


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
    if not text:
        return text
    text = _GH_LINK.sub("<link>", text)
    text = _ISSUE_REF.sub("#ref", text)
    text = _SHA.sub(lambda m: "<sha>" if _looks_like_sha(m.group(0)) else m.group(0), text)
    return text


def _scrub_titles(items, key):
    out = []
    for item in items or []:
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
    ctx["releases"] = _scrub_titles(ctx.get("releases"), "name")
    ctx["_forward_signal_scrubbed"] = True
    return ctx
