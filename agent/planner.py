"""Step 3a: plan the next N maintainer actions / PRs, consistent with the philosophy.

The plan is what the benchmark judges against the revealed history — on direction/theme,
not on naming the exact PRs that happened.
"""

from __future__ import annotations

import json
import logging
import re

from agent.context import context_for_agent

logger = logging.getLogger(__name__)

# Generic verbs / queue words dropped before matching a plan item to a PR, so the match
# keys on the real subject ("loader race") not the framing ("review the PR to fix ...").
_STOPWORDS = frozenset({
    "add", "added", "adds", "fix", "fixes", "fixed", "update", "updates", "updated",
    "improve", "improves", "support", "make", "use", "using", "new", "the", "and", "for",
    "with", "into", "from", "via", "pull", "request", "requests", "review", "reviews",
    "merge", "merges", "approve", "change", "changes", "land", "ship", "issue", "feature",
    "bugfix", "refactor", "docs", "release", "work", "that", "this",
})

# Word-boundary match so an incidental substring ("preview" ⊃ "review", "emergency" ⊃
# "merge") doesn't misclassify greenfield work as an existing review item. Anchored only
# at the start, so real suffixes ("reviews", "merged", "approved") still count.
_REVIEW_MARKER_RE = re.compile(
    r"\b(?:review|merge|approve|request\s+changes|pull\s+request)",
    re.I,
)
# A bare "#N" denotes a pull request only when a review verb *governs* it — the verb is
# directly followed by the number, allowing only connective words in between ("Review #7",
# "Merge and land #7", "Review the PR #7"). A review word that merely appears elsewhere in a
# feature description ("improve the code review workflow, #2 on the roadmap") does not qualify:
# there the "#2" is a roadmap ordinal, not a reference to PR #2.
_REVIEW_REF_RE = re.compile(
    r"\b(?:review|reviewing|reviewed|merge|merging|merged|approve|approving|approved)\b"
    r"(?:\s+(?:and|or|then|the|a|an|this|that|it|pr|pull|request|changes))*"
    r"\s+#?\s*\d+\b",
    re.I,
)
# Explicit PR references: "#7", "PR #7", "pull request 7"
_PR_NUMBER = re.compile(
    r"(?:#\s*(\d+)\b|(?:pull\s+request|pr)\s+#?\s*(\d+)\b)",
    re.I,
)
# Minimum PR-subject phrase length for substring matching — shorter titles are ambiguous.
_MIN_SUBJECT_PHRASE = 8

_PLAN_KINDS = frozenset({
    "feature", "bugfix", "refactor", "docs", "release", "dep", "triage",
})

SYSTEM = (
    "You are an experienced repository maintainer. Given the repo state and its inferred "
    "maintainer philosophy, plan the next concrete maintainer actions / PRs that should "
    "happen, in priority order. When open pull requests are waiting for review, a strong "
    "maintainer clears or explicitly schedules that queue before unrelated greenfield work. "
    "Stay consistent with the philosophy. Respond ONLY with JSON."
)


def _pr_title(pr: dict) -> str:
    """Return a stripped PR title when it is a string; else empty."""
    if not isinstance(pr, dict):
        return ""
    title = pr.get("title")
    return title.strip() if isinstance(title, str) else ""


def _pr_dedup_key(pr: dict):
    """Return a stable dedup key for an open PR in queue reconciliation.

    Numbered PRs key on ``number``; numberless PRs key on title so two distinct
    queue entries without a ``number`` do not collapse onto a shared ``None``.
    """
    if not isinstance(pr, dict):
        return None
    number = pr.get("number")
    if number is not None:
        return ("number", number)
    title = _pr_title(pr)
    return ("title", title) if title else None


def _open_prs_list(context: dict) -> list:
    """Return ``open_prs`` when it is a list; otherwise treat as no PR queue.

    A truthy non-list (``42``, ``True``, a bare dict) must not reach ``for p in open_prs``
    or malformed frozen context aborts queue reconciliation.
    """
    raw = (context or {}).get("open_prs")
    return raw if isinstance(raw, list) else []


def _pr_queue_note(context: dict) -> str:
    prs = [p for p in _open_prs_list(context) if _pr_title(p)]
    if not prs:
        return ""
    lines = [f"- #{p.get('number', '?')}: {_pr_title(p)}" for p in prs]
    return (
        f"\nOpen pull requests awaiting review ({len(lines)}):\n"
        + "\n".join(lines)
        + "\n\nInclude at least one plan item to review, merge, or request changes on a "
        "queued pull request when the queue above is non-empty.\n"
    )


def _offline_plan_stub(context: dict, n: int) -> list:
    """Deterministic offline plan: prioritize the visible PR queue when present."""
    items = []
    for pr in _open_prs_list(context):
        title = _pr_title(pr)
        if not title:
            continue
        items.append({
            "title": f"Review pull request: {title}",
            "kind": "triage",
            "rationale": "open PR awaiting maintainer review",
            "theme": "PR queue",
        })
    if not items:
        items.append({
            "title": "offline stub action",
            "kind": "triage",
            "rationale": "offline",
            "theme": "offline",
        })
    return items[:n]


def _pr_queue(context: dict) -> list:
    return [
        p for p in _open_prs_list(context)
        if isinstance(p, dict) and _pr_title(p)
    ]


def _significant_tokens(text: str) -> set:
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    return {
        t for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) > 2 and t not in _STOPWORDS
    }


def _pr_reference(*texts: str):
    """Return ``(pr_number, qualified)`` for the most authoritative PR reference in the texts.

    ``qualified`` is True for an unambiguous ``"PR #N"`` / ``"pull request N"`` phrasing, and
    False for a bare ``"#N"`` — which is frequently an ordinal ("the #1 requested feature",
    "our #7 priority") rather than a pull-request reference, so callers must content-validate a
    bare match before trusting it. A qualified match anywhere in the texts always wins, even if
    a bare match appears earlier — otherwise an incidental ordinal ("our #1 priority") ahead of
    a genuine "PR #7" reference in the same sentence would shadow it. Only when no qualified
    match exists anywhere does the first bare match apply. Returns ``(None, False)`` when no
    reference is present.
    """
    bare = None
    for text in texts:
        if not text:
            continue
        for match in _PR_NUMBER.finditer(text):
            if match.group(2):        # "PR #N" / "pull request N" — unambiguous, always wins
                return int(match.group(2)), True
            if bare is None and match.group(1):  # bare "#N" — could be an ordinal
                bare = int(match.group(1))
    return (bare, False) if bare is not None else (None, False)


def _explicit_pr_number(*texts: str) -> int | None:
    """The PR number referenced in plan text, if any (qualified or bare — see ``_pr_reference``)."""
    return _pr_reference(*texts)[0]


def _reads_as_pr_reference(item: dict) -> bool:
    """True when a review verb in the item's text *governs* a bare ``#N``, so the ``#N`` denotes a
    pull request rather than an ordinal ranking numeral ("our #1 priority").

    The verb must be followed by the number (allowing only connective words in between), so a
    review word that merely appears elsewhere in a feature description — e.g. "improve the code
    review workflow, #2 on the roadmap" — does not turn an unrelated ordinal into a PR reference.
    """
    blob = f"{item.get('title', '')} {item.get('rationale', '')}"
    return bool(_REVIEW_REF_RE.search(blob))


def _title_contains_pr_subject(item: dict, pr: dict) -> bool:
    """True when the plan item quotes the PR's subject as a phrase (not a lone token)."""
    subject = _pr_title(pr).lower()
    if len(subject) < _MIN_SUBJECT_PHRASE:
        return False
    blob = f"{item.get('title', '')} {item.get('rationale', '')}".lower()
    return subject in blob


def _pr_content_matches(item: dict, pr: dict) -> bool:
    """True when a plan item's content actually corresponds to a PR — it quotes the PR's
    subject phrase, or shares a strong token overlap on the same terms ``_matched_pr`` uses,
    independent of any ``#N`` it mentions.

    Applies the same guards as the overlap path in ``_matched_pr`` so a bare ``#N`` is never
    trusted on a weaker signal than ordinary matching: a single-token PR title is too
    ambiguous to match on overlap alone, and at least two significant shared tokens are
    required.
    """
    if _title_contains_pr_subject(item, pr):
        return True
    itoks = _significant_tokens(item.get("title", "")) | _significant_tokens(item.get("theme", ""))
    ptoks = _significant_tokens(_pr_title(pr))
    if len(ptoks) < 2:
        return False  # single-token PR titles: overlap-only matching disabled
    return len(itoks & ptoks) >= 2


def _matched_pr(item: dict, prs: list):
    """The open PR a plan item is about, or None.

    Matching order: explicit ``#N`` reference, then full-subject phrase (the longest
    matching title when several nested titles are quoted), then significant-token
    overlap. One-word PR titles never match on overlap alone — they are too
    ambiguous when the queue grows. An explicit ``#N`` that names a PR no longer in the
    queue is treated as stale: the item is **not** matched against a different open PR
    via fallback, since the author already committed to a specific number.
    """
    by_number = {p.get("number"): p for p in prs if p.get("number") is not None}

    ref, qualified = _pr_reference(item.get("title", ""), item.get("rationale", ""))
    if ref is not None:
        pr = by_number.get(ref)
        # A qualified "PR #N" is authoritative (even when stale -> None, which suppresses
        # fallback matching). A bare "#N" is trusted only when the item actually reads as a PR
        # reference or its content matches the PR; otherwise "#N" is an ordinal ("the #1
        # feature") and must not hijack an unrelated open PR — fall through to content matching.
        if qualified or _reads_as_pr_reference(item) or (pr is not None and _pr_content_matches(item, pr)):
            return pr

    # Full-subject phrase match. Nested titles ("Add streaming export" is a substring of
    # "Add streaming export docs") can both appear in the plan text; prefer the longest
    # matching title so the more specific PR wins instead of whichever comes first in queue
    # order.
    subject_matches = [pr for pr in prs if _title_contains_pr_subject(item, pr)]
    if subject_matches:
        return max(subject_matches, key=lambda pr: len(_pr_title(pr)))

    itoks = _significant_tokens(item.get("title", "")) | _significant_tokens(item.get("theme", ""))
    if not itoks:
        return None

    best, best_overlap = None, 0
    for pr in prs:
        ptoks = _significant_tokens(_pr_title(pr))
        if not ptoks:
            continue
        overlap = len(itoks & ptoks)
        if overlap == 0:
            continue
        n_pr = len(ptoks)
        if n_pr == 1:
            # Single-token PR titles are ambiguous — overlap-only matching is disabled.
            continue
        if overlap > best_overlap and (overlap >= 2 or overlap == n_pr):
            best, best_overlap = pr, overlap
    return best


def _is_review_item(item: dict) -> bool:
    """True when the item already frames the work as reviewing/triaging a PR."""
    if (item.get("kind") or "").strip().lower() == "triage":
        return True
    return bool(_REVIEW_MARKER_RE.search(item.get("title") or ""))


def _normalize_text_field(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _normalize_files(value) -> list:
    """Coerce ``files`` to the documented ``list[str]`` contract."""
    if value is None:
        return []
    if isinstance(value, str):
        path = value.strip()
        return [path] if path else []
    if isinstance(value, list):
        out = []
        for item in value:
            if item is None:
                continue
            path = item.strip() if isinstance(item, str) else str(item).strip()
            if path:
                out.append(path)
        return out
    logger.warning(
        "plan: LLM returned a non-list files field (%s: %r); dropping",
        type(value).__name__, value,
    )
    return []


def _normalize_plan_item(item) -> dict | None:
    """Coerce one LLM plan item onto the documented shape, or drop it."""
    if not isinstance(item, dict):
        return None
    title = _normalize_text_field(item.get("title"))
    if not title:
        return None
    kind = item.get("kind")
    if isinstance(kind, str):
        kind = kind.strip().lower()
    else:
        kind = ""
    if kind not in _PLAN_KINDS:
        kind = "triage"
    normalized = {
        "title": title,
        "kind": kind,
    }
    rationale = _normalize_text_field(item.get("rationale"))
    theme = _normalize_text_field(item.get("theme"))
    if rationale:
        normalized["rationale"] = rationale
    if theme:
        normalized["theme"] = theme
    files = _normalize_files(item.get("files"))
    if files:
        normalized["files"] = files
    if "restates_pr" in item:
        normalized["restates_pr"] = item["restates_pr"]
    return normalized


def _plan_list(plan, field: str = "plan") -> list:
    """Return ``plan`` when it is a list; otherwise treat as no plan items.

    A truthy non-list must not reach ``for item in plan`` or malformed LLM / caller input
    aborts queue reconciliation (#545).
    """
    if isinstance(plan, list):
        return plan
    if plan is not None:
        logger.warning(
            "planner: %s is %s, not a list; treating as empty",
            field,
            type(plan).__name__,
        )
    return []


def _normalize_plan(plan) -> list:
    out = []
    for item in _plan_list(plan):
        normalized = _normalize_plan_item(item)
        if normalized is not None:
            out.append(normalized)
    return out


def reconcile_plan_with_queue(plan, context: dict, n: int) -> list:
    """Make the plan honor the open-PR queue, deterministically and independent of the LLM.

    Guards three failure modes when an LLM disregards the provided queue:
    - **Duplicates in flight**: an item that restates an open PR's work is down-weighted to a
      `triage` review item and flagged with `restates_pr`, instead of being planned as new work.
    - **Redundant items**: multiple items targeting the same PR are collapsed to the first.
    - **Ignored queue**: if no item addresses any open PR, a review item for the top PR is
      prepended so the queue is never silently skipped.

    With no open PRs (or none matched) the plan passes through unchanged, capped to `n`.
    """
    prs = _pr_queue(context)
    plan = _normalize_plan(plan)
    if not prs:
        return plan[:n]

    out, seen_prs, addressed = [], set(), False
    for item in plan:
        pr = _matched_pr(item, prs)
        if pr is not None:
            number = pr.get("number")
            dedup_key = _pr_dedup_key(pr)
            if dedup_key is not None and dedup_key in seen_prs:
                continue
            if dedup_key is not None:
                seen_prs.add(dedup_key)
            addressed = True
            if not _is_review_item(item):
                item = {
                    **item,
                    "kind": "triage",
                    "restates_pr": number,
                    "rationale": (
                        f"restates open PR #{number} already in flight; review it instead of "
                        "duplicating the work"
                    ),
                }
        out.append(item)

    if not addressed:
        top = prs[0]
        out.insert(0, {
            "title": f"Review pull request #{top.get('number', '?')}: {_pr_title(top)}",
            "kind": "triage",
            "restates_pr": top.get("number"),
            "rationale": (
                "the open PR queue was omitted from the plan; a strong maintainer clears or "
                "schedules review before unrelated work"
            ),
            "theme": "PR queue",
        })
    return out[:n]


def plan_next_actions(context: dict, philosophy: dict, n: int, llm) -> list:
    if not isinstance(context, dict):
        return _offline_plan_stub({}, n)
    user = (
        f"Repository philosophy:\n{json.dumps(philosophy, indent=1)[:4000]}\n\n"
        f"Repository state:\n{_render(context)}\n"
        f"{_pr_queue_note(context)}\n"
        f"Plan the next {n} maintainer actions/PRs. Return a JSON list; each item:\n"
        '  "title": short imperative title,\n'
        '  "kind": one of "feature","bugfix","refactor","docs","release","dep","triage",\n'
        '  "rationale": why this, now, given the philosophy,\n'
        '  "theme": the higher-level direction this advances.'
    )
    stub = _offline_plan_stub(context, n)
    plan = llm.chat_json(SYSTEM, user, stub=stub)
    if isinstance(plan, dict):  # tolerate {"plan": [...]}
        wrapped = _plan_list(plan.get("plan"), "plan")
        plan = wrapped or _plan_list(plan.get("actions"), "actions")
    plan = _normalize_plan(plan if isinstance(plan, list) else [])
    return reconcile_plan_with_queue(plan, context, n)


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
