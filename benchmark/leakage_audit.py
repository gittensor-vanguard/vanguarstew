"""Audit a frozen-at-T context for residual forward-reference leaks.

``benchmark.leakage.scrub_context`` masks forward references (issue/PR backlinks, GitHub
deep-links, raw SHAs) in the free-text fields of a frozen context before the agent sees it.
This is the *verification* side: scan a context and report any field that still carries a
forward reference, so the leakage controls can be checked — "leakage audit clean" (ROADMAP M4)
— in CI or before a run, and so a context that skipped (or only partially applied) the scrubber
is caught rather than silently shipped to the agent.

It is deliberately built on the scrubber's **public** ``strip_forward_refs`` rather than its
internal patterns: a field is "leaky" exactly when scrubbing it would change it, so the audit
can never drift from what the scrubber actually masks. Pure detection: no I/O, never mutates the
context, and tolerant of a malformed context (a non-dict item or non-string field is skipped,
not a crash).

The scanned fields mirror ``scrub_context`` exactly:

- ``readme_excerpt`` (a string);
- ``recent_commits[].subject``;
- ``open_issues[].title`` / ``open_prs[].title`` / ``milestones[].title``;
- ``releases[].tag`` and ``releases[].name``.
"""

from __future__ import annotations

from benchmark.leakage import strip_forward_refs

# (context key, item text key) for the list-of-dicts fields scrub_context scrubs. ``releases``
# carries two candidate text keys (``tag`` on the git-freeze path, ``name`` on the API path).
_LIST_FIELDS = (
    ("recent_commits", "subject"),
    ("open_issues", "title"),
    ("open_prs", "title"),
    ("milestones", "title"),
    ("releases", "tag"),
    ("releases", "name"),
)

_SNIPPET = 120


def _leak(field: str, text: str) -> dict | None:
    """A finding for ``text`` when it carries a forward reference, else ``None``.

    A string is leaky exactly when the (public) scrubber would change it. Non-string values
    carry no scrubbable text, so they are clean by definition.
    """
    if not isinstance(text, str) or not text:
        return None
    scrubbed = strip_forward_refs(text)
    if scrubbed == text:
        return None
    return {"field": field, "text": text[:_SNIPPET], "scrubbed": scrubbed[:_SNIPPET]}


def audit_context(context) -> list:
    """Return a list of residual forward-reference findings in a frozen ``context``.

    Each finding is ``{"field", "text", "scrubbed"}`` where ``field`` locates the leak (e.g.
    ``"recent_commits[2].subject"``). An empty list means the context is leakage-clean over
    every field the scrubber covers.
    """
    if not isinstance(context, dict):
        return []
    findings = []

    readme = _leak("readme_excerpt", context.get("readme_excerpt"))
    if readme is not None:
        findings.append(readme)

    for key, text_key in _LIST_FIELDS:
        items = context.get(key)
        if not isinstance(items, list):
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict) or text_key not in item:
                continue
            finding = _leak(f"{key}[{index}].{text_key}", item.get(text_key))
            if finding is not None:
                findings.append(finding)
    return findings


def is_clean(context) -> bool:
    """True when ``context`` carries no residual forward reference in any scrubbed field."""
    return not audit_context(context)


def audit_headline(findings) -> str:
    """A one-line human summary of an :func:`audit_context` result."""
    if not findings:
        return "leakage audit: clean"
    fields = ", ".join(dict.fromkeys(f["field"] for f in findings))
    return f"leakage audit: {len(findings)} leak(s) in {fields}"
