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
# directly followed by the number, allowing only connective words and follow-through action verbs
# in between ("Review #7", "Merge and land #7", "Review then ship #7", "Review the PR #7"). A review
# word that merely appears elsewhere in a feature description ("improve the code review workflow, #2
# on the roadmap") does not qualify: there "workflow" is a noun (not a connective or action verb) so
# the run stops before "#2", leaving it a roadmap ordinal, not a reference to PR #2.
_REVIEW_REF_RE = re.compile(
    r"\b(?:review|reviewing|reviewed|merge|merging|merged|approve|approving|approved)\b"
    r"(?:\s+(?:and|or|then|the|a|an|this|that|it|pr|pull|request|changes"
    r"|land|landed|ship|shipped|finish|finished|complete|completed|finalize|finalized"
    r"|close|closed|deliver|delivered|do|done|handle|handled|address|addressed"
    r"|resolve|resolved|get|wrap|submit|submitted|apply|applied|integrate|integrated))*"
    r"\s+#?\s*(\d+)\b",
    re.I,
)
# Explicit PR references: "#7", "PR #7", "pull request 7"
_PR_NUMBER = re.compile(
    r"(?:#\s*(\d+)\b|(?:pull\s+request|pr)\s+#?\s*(\d+)\b)",
    re.I,
)
# Minimum PR-subject phrase length for substring matching — shorter titles are ambiguous.
_MIN_SUBJECT_PHRASE = 8

# Plan-item `kind` vocabulary. Every entry except "triage" maps to a normalized commit kind in
# the objective anchor's `benchmark/score.py::_PLAN_KIND`, so a plan can name any kind the
# anchor actually scores. "triage" is a maintainer action, not a commit kind, and deliberately
# maps to nothing there — it is the fallback for an item that names no recognizable kind.
_PLAN_KINDS = frozenset({
    "feature", "bugfix", "refactor", "docs", "release", "dep", "triage",
    "build", "ci", "test", "perf", "style", "revert",
})

# Conventional-Commit prefix on a commit subject: "feat:", "fix(scope):", "docs!:". This block
# mirrors the objective anchor's classifier (benchmark/score.py `commit_kind`) in simplified
# form, mapped into the planner's own `kind` vocabulary. We deliberately do NOT import from
# ``benchmark/`` (``agent/`` must not depend on it — a miner-only split is planned); keep the
# two aligned, as agent/context.py already does for forward-reference scrubbing.
_CC_PREFIX_RE = re.compile(r"^\s*([a-z]+)(?:\([^)]*\))?!?:", re.I)

# Conventional-Commit type -> plan-item "kind" (_PLAN_KINDS). Every type the anchor's own
# classifier (`benchmark/score.py::_COMMIT_KIND`) recognizes has an entry here, so a kind the
# anchor reads out of a subject is one the plan can name back. No type is dropped for lack of
# an equivalent: a dropped type is invisible to `_recent_kinds_note`, which then describes a
# history the repo does not have, and unnameable by the plan, which pins `kind_recall` at 0.000
# for any repo whose work lands under it.
_CC_TYPE_TO_PLAN_KIND = {
    "feat": "feature", "feature": "feature",
    "fix": "bugfix", "bugfix": "bugfix", "bug": "bugfix",
    "docs": "docs", "doc": "docs",
    "refactor": "refactor",
    "release": "release",
    "chore": "dep", "deps": "dep", "dep": "dep",
    "build": "build",
    "ci": "ci",
    "test": "test", "tests": "test",
    "perf": "perf",
    "style": "style",
    "revert": "revert",
}

# Release tooling (standard-version / release-please) cuts versions under a chore/build type:
# "chore(release): 1.4.0", "chore(main): release 1.2.3", "build(release): 2.0.0". Those are
# release actions, not dependency chores, so they must count toward "release" — exactly how
# the anchor classifies them. The body regex matches benchmark/score.py `_RELEASE_TAG_SUBJECT`.
_RELEASE_TOOLING_TYPES = frozenset({"chore", "build"})
_RELEASE_CUT_BODY_RE = re.compile(r"^\s*(?:release[\s:_-]*)?v?\d+\.\d+(?:\.\d+)?\b", re.I)

SYSTEM = (
    "You are an experienced repository maintainer. Given the repo state and its inferred "
    "maintainer philosophy, plan the next concrete maintainer actions / PRs that should "
    "happen, in priority order. When open pull requests are waiting for review, a strong "
    "maintainer clears or explicitly schedules that queue before unrelated greenfield work. "
    "Stay consistent with the philosophy. Respond ONLY with JSON."
)

# Prompt fragments for the plan-item schema and objective-anchor guidance. Kept as named
# constants so tests can lock the contract without parsing full LLM prompts.
PLAN_ITEM_SCHEMA = (
    '  "title": short imperative title,\n'
    '  "kind": one of "feature","bugfix","refactor","docs","release","dep","build","ci",\n'
    '          "test","perf","style","revert","triage",\n'
    '  "rationale": why this, now, given the philosophy,\n'
    '  "theme": the higher-level direction this advances,\n'
    '  "files": optional list of repo-relative paths or top-level modules likely touched.'
)

OBJECTIVE_ANCHOR_GUIDANCE = (
    "Concrete specificity matters: for each non-triage item, include `files` naming the "
    "top-level module or paths you expect to change (e.g. `src/loader.py`, `docs/`, `tests/`). "
    "Pick `kind` to match the maintainer commit type the action would produce "
    "(bugfix/fix, feature/feat, docs, release, refactor, dep, build, ci, test, perf, style, "
    "revert). When several kinds recur in recent history, plan separate items so each kind is "
    "covered."
)

RELEASE_CADENCE_GUIDANCE = (
    "Recent history shows release-cadence activity — include one `release`-kind item in the plan."
)

REPO_LAYOUT_GUIDANCE = (
    "Ground each non-triage item's `files` in that listing — name the entries the item actually "
    "touches (a path under a listed directory is fine), rather than a conventional source "
    "layout this repository may not have."
)


def _pr_title(pr: dict) -> str:
    """Return a stripped PR title when it is a string; else empty."""
    if not isinstance(pr, dict):
        return ""
    title = pr.get("title")
    return title.strip() if isinstance(title, str) else ""


def _pr_number(pr: dict):
    """Return an open PR's ``number`` when it is a usable scalar int, else None.

    The frozen queue is LLM/GitHub-derived JSON, so ``number`` can arrive as a non-scalar
    (a list or dict). Such a value is *unhashable*, and both queue-reconciliation keyings —
    the ``by_number`` lookup in ``_matched_pr`` and the ``seen_prs`` set via
    ``_pr_dedup_key`` — would raise ``TypeError: unhashable type`` and abort the whole plan
    step. Treat a non-int ``number`` as numberless (dedup falls back to title), mirroring the
    existing numberless handling rather than crashing. ``bool`` is rejected too: it is never a
    real PR number and would alias 0/1.
    """
    if not isinstance(pr, dict):
        return None
    number = pr.get("number")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return number


def _pr_dedup_key(pr: dict):
    """Return a stable dedup key for an open PR in queue reconciliation.

    Numbered PRs key on ``number``; numberless PRs key on title so two distinct
    queue entries without a ``number`` do not collapse onto a shared ``None``.
    """
    if not isinstance(pr, dict):
        return None
    number = _pr_number(pr)
    if number is not None:
        return ("number", number)
    title = _pr_title(pr)
    return ("title", title) if title else None


def _safe_prs(context: dict) -> list:
    """Return the planner-visible open-PR queue, or ``[]`` when unavailable or untrusted.

    Fail-closed on ``_issues_truncated is True`` (#722): a partial backlog must not drive
    queue notes, offline stubs, or reconciliation. A non-list ``open_prs`` value is treated
    as no queue rather than aborting the planner path.
    """
    if not isinstance(context, dict):
        return []
    if context.get("_issues_truncated") is True:
        return []
    raw = context.get("open_prs")
    return raw if isinstance(raw, list) else []


def _commit_plan_kind(subject):
    """The plan-vocabulary kind a recent-commit subject evidences, or None.

    Reads the Conventional-Commit prefix; a version-cut subject under a release-tooling type
    ("chore(release): 1.4.0") reads as ``release`` rather than ``dep``. Merge commits and
    prefix-less subjects carry no reliable kind, and a non-string subject (malformed frozen
    context) is ignored rather than raising inside ``re``.
    """
    if not isinstance(subject, str):
        return None
    m = _CC_PREFIX_RE.match(subject)
    if not m:
        return None
    cc_type = m.group(1).lower()
    if cc_type in _RELEASE_TOOLING_TYPES:
        body = subject[m.end():].lstrip(" :\t")
        if _RELEASE_CUT_BODY_RE.match(body):
            return "release"
    return _CC_TYPE_TO_PLAN_KIND.get(cc_type)


def _recent_commits(context: dict) -> list:
    """The frozen recent-commit list, or ``[]`` when absent or malformed."""
    if not isinstance(context, dict):
        return []
    raw = context.get("recent_commits")
    return raw if isinstance(raw, list) else []


def _recent_kind_counts(context: dict) -> list:
    """``(kind, count)`` pairs over recent commits, most frequent first, ties alphabetical."""
    counts: dict = {}
    for commit in _recent_commits(context):
        if not isinstance(commit, dict):
            continue
        kind = _commit_plan_kind(commit.get("subject"))
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _recent_kinds_note(context: dict) -> str:
    """Prompt note surfacing the repo's recent kind mix so planned kinds track history (#1387).

    Derived from the full frozen ``recent_commits`` list — unlike the JSON dump in ``_render``,
    which is truncated to 12000 chars, so the tail of a long history still counts here. All
    recent commits are considered, not one author's: the revealed window the plan is scored
    against is repo-wide.
    """
    counts = _recent_kind_counts(context)
    if not counts:
        return ""
    mix = ", ".join(f"{kind} ({n})" for kind, n in counts)
    return (
        f"\nRecent maintainer activity by kind, from Conventional-Commit subjects: {mix}.\n"
        "Near-future maintainer work usually continues this mix. Unless the philosophy or "
        'the PR queue argues otherwise, make the plan items\' "kind" values collectively '
        "cover the recurring kinds above, and keep `files` on every non-triage item.\n"
    )


def _release_cadence_signal(context: dict) -> bool:
    """True when recent commits show a release cut (mirrors heuristic_plan cadence)."""
    return any(
        _commit_plan_kind(commit.get("subject")) == "release"
        for commit in _recent_commits(context)
        if isinstance(commit, dict)
    )


def _release_cadence_note(context: dict) -> str:
    """Inject release-item guidance only when history evidences release cadence."""
    if not _release_cadence_signal(context):
        return ""
    return f"\n{RELEASE_CADENCE_GUIDANCE}\n"


def _repo_layout(context: dict) -> list:
    """The frozen checkout's top-level entries, or ``[]`` when absent or malformed.

    ``repo_layout`` is derived by ``agent.context.load_context``, but the planner is also
    called directly with hand-built context (tests, callers, older frozen artifacts), so the
    shape is guarded here rather than assumed: a non-list value, and any non-string or blank
    entry within it, is dropped instead of reaching the prompt.

    An entry carrying a rendering separator — a comma (the delimiter the note joins on) or a
    newline — is dropped too. Repository filenames are not authored by this project, and the
    note is the one place in ``agent/`` that renders them into a prompt: a name containing a
    newline would otherwise occupy its own prompt line as free-standing text, and one
    containing a comma would read as two entries while the stated count said otherwise.
    """
    if not isinstance(context, dict):
        return []
    raw = context.get("repo_layout")
    if not isinstance(raw, list):
        if raw is not None:
            logger.warning(
                "planner: repo_layout is %s, not a list; treating as empty",
                type(raw).__name__,
            )
        return []
    entries = []
    for entry in raw:
        if not isinstance(entry, str):
            continue
        name = entry.strip()
        if not name or any(sep in name for sep in (",", "\n", "\r")):
            continue
        entries.append(name)
    return entries


def _repo_layout_note(context: dict) -> str:
    """Prompt note grounding the plan's `files` in the repo's real top-level entries at T.

    Without it the only concrete guidance is ``OBJECTIVE_ANCHOR_GUIDANCE``'s illustrative
    examples (`src/loader.py`, `docs/`, `tests/`), which name a conventional source layout many
    repositories do not have — so `files` gets filled with plausible-looking paths that are not
    in the tree. Empty when the layout could not be read, so the prompt is unchanged rather
    than carrying an empty list.

    The note describes the listing as the repository's top-level entries and claims nothing
    more. It deliberately does not assert that these are the only paths that exist: the listing
    is top-level only (nested paths are legitimate and `OBJECTIVE_ANCHOR_GUIDANCE` asks for
    them) and it is capped, so an exhaustiveness claim would be false — and would tell the plan
    that a real module it had correctly identified does not exist.
    """
    entries = _repo_layout(context)
    if not entries:
        return ""
    return (
        f"\nRepository layout at the freeze commit — its top-level entries "
        f"({len(entries)}): {', '.join(entries)}.\n"
        f"{REPO_LAYOUT_GUIDANCE}\n"
    )


def _pr_queue_note(context: dict) -> str:
    prs = [p for p in _safe_prs(context) if _pr_title(p)]
    if not prs:
        return ""
    lines = []
    for p in prs:
        num = _pr_number(p)
        lines.append(f"- #{num if num is not None else '?'}: {_pr_title(p)}")
    return (
        f"\nOpen pull requests awaiting review ({len(lines)}):\n"
        + "\n".join(lines)
        + "\n\nInclude at least one plan item to review, merge, or request changes on a "
        "queued pull request when the queue above is non-empty.\n"
    )


def _offline_plan_stub(context: dict, n: int) -> list:
    """Deterministic offline plan: prioritize the visible PR queue when present."""
    items = []
    for pr in _safe_prs(context):
        title = _pr_title(pr)
        if not title:
            continue
        # Include the PR number so ``reconcile_plan_with_queue`` -> ``_matched_pr`` re-associates
        # this stub item with its PR via the ``#N`` reference. Without it, a short (< 8 char) or
        # single-significant-token title (e.g. "Fix bug") matches on neither the subject-phrase
        # nor token-overlap path, so reconcile treats the queue as unaddressed and prepends a
        # *second* review item for the same PR. Mirrors the numbered title reconcile itself uses.
        number = _pr_number(pr)
        heading = f"Review pull request #{number}" if number is not None else "Review pull request"
        items.append({
            "title": f"{heading}: {title}",
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
        p for p in _safe_prs(context)
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


def _review_governed_pr_number(item: dict) -> int | None:
    """The bare ``#N`` a review verb governs in the item text, or ``None`` when none."""
    blob = f"{item.get('title', '')} {item.get('rationale', '')}"
    match = _REVIEW_REF_RE.search(blob)
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


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
    by_number = {_pr_number(p): p for p in prs if _pr_number(p) is not None}

    ref, qualified = _pr_reference(item.get("title", ""), item.get("rationale", ""))
    if ref is not None:
        lookup = ref
        # A review verb may govern a *later* bare "#N" while an earlier "#N" is an ordinal
        # ("Deliver our #1 priority, then review #7") — resolve the governed number, not the
        # first bare match from ``_pr_reference``.
        if not qualified and _reads_as_pr_reference(item):
            governed = _review_governed_pr_number(item)
            if governed is not None:
                lookup = governed
        pr = by_number.get(lookup)
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
            number = _pr_number(pr)
            dedup_key = _pr_dedup_key(pr)
            if dedup_key is not None and dedup_key in seen_prs:
                continue
            if dedup_key is not None:
                seen_prs.add(dedup_key)
            addressed = True
            if not _is_review_item(item):
                if number is not None:
                    rationale = (f"restates open PR #{number} already in flight; review it "
                                 "instead of duplicating the work")
                else:
                    rationale = ("restates an open PR already in flight; review it instead "
                                 "of duplicating the work")
                item = {
                    **item,
                    "kind": "triage",
                    "restates_pr": number,
                    "rationale": rationale,
                }
        out.append(item)

    if not addressed:
        top = prs[0]
        top_number = _pr_number(top)
        out.insert(0, {
            "title": f"Review pull request #{top_number if top_number is not None else '?'}: "
                     f"{_pr_title(top)}",
            "kind": "triage",
            "restates_pr": top_number,
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
        f"{_repo_layout_note(context)}"
        f"{_recent_kinds_note(context)}"
        f"{_release_cadence_note(context)}"
        f"{_pr_queue_note(context)}\n"
        f"Plan the next {n} maintainer actions/PRs. Return a JSON list; each item:\n"
        f"{PLAN_ITEM_SCHEMA}\n\n"
        f"{OBJECTIVE_ANCHOR_GUIDANCE}"
    )
    stub = _offline_plan_stub(context, n)
    plan = llm.chat_json(SYSTEM, user, stub=stub)
    if isinstance(plan, dict):  # tolerate {"plan": [...]}
        raw_plan = plan.get("plan")
        # An explicit "plan" key — even an empty list — must be honored and
        # not silently replaced by a stale "actions" fallback (#1011).  A
        # non-list "plan" still gets the existing warning + fallback path.
        if isinstance(raw_plan, list):
            plan = raw_plan
        elif "plan" in plan:
            plan = _plan_list(raw_plan, "plan") or _plan_list(plan.get("actions"), "actions")
        else:
            plan = _plan_list(plan.get("actions"), "actions")
    plan = _normalize_plan(plan if isinstance(plan, list) else [])
    return reconcile_plan_with_queue(plan, context, n)


def _render(context: dict) -> str:
    ctx = context_for_agent(context)
    keep = {k: ctx.get(k) for k in (
        "frozen_at", "recent_commits", "open_issues", "open_prs",
        "labels", "milestones", "releases", "readme_excerpt",
    )}
    return json.dumps(keep, indent=1)[:12000]
