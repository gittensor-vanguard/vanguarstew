"""Audit a frozen context for residual forward-reference leaks.

``scrub_context`` masks issue/PR backlinks, GitHub deep-links, and raw SHAs before the agent
sees a frozen context. This module verifies that work: a field is leaky exactly when
:func:`benchmark.leakage.strip_forward_refs` would change it, so the audit cannot drift from
the scrubber. Pure detection — no I/O, never mutates its input, and tolerates malformed
context shapes.
"""

from __future__ import annotations

import logging

from benchmark.leakage import _scrub_list, strip_forward_refs

logger = logging.getLogger(__name__)


def _finding(location: str, value: str) -> dict:
    return {"location": location, "value": value, "masked": strip_forward_refs(value)}


def _audit_text(location: str, value, findings: list) -> None:
    if not isinstance(value, str) or not value:
        return
    masked = strip_forward_refs(value)
    if masked != value:
        findings.append(_finding(location, value))


def _audit_titled_list(prefix: str, items, key: str, findings: list) -> None:
    for index, item in enumerate(_scrub_list(items)):
        if not isinstance(item, dict) or key not in item:
            continue
        _audit_text(f"{prefix}[{index}].{key}", item.get(key), findings)


def _findings_list(findings) -> list:
    """Return ``findings`` when it is a list; otherwise treat as no audit findings."""
    if isinstance(findings, list):
        return findings
    if findings is not None:
        logger.warning(
            "leakage_audit: findings is %s, not a list; treating as empty",
            type(findings).__name__,
        )
    return []


def audit_context(context) -> list:
    """Return findings for every scrubbable field that still carries a forward reference.

    Each finding is ``{location, value, masked}``. An empty list means the context is clean.
    Non-dict or malformed contexts never raise — they simply yield no findings (or only what
    can be read safely).
    """
    findings = []
    if not isinstance(context, dict):
        return findings

    _audit_text("readme_excerpt", context.get("readme_excerpt"), findings)
    _audit_titled_list("recent_commits", context.get("recent_commits"), "subject", findings)
    _audit_titled_list("open_issues", context.get("open_issues"), "title", findings)
    _audit_titled_list("open_prs", context.get("open_prs"), "title", findings)
    _audit_titled_list("milestones", context.get("milestones"), "title", findings)
    _audit_titled_list("releases", context.get("releases"), "tag", findings)
    _audit_titled_list("releases", context.get("releases"), "name", findings)
    return findings


def is_clean(context) -> bool:
    """True when ``audit_context`` finds no residual forward references."""
    return not audit_context(context)


def audit_headline(findings: list) -> str:
    """One-line human summary of an :func:`audit_context` result."""
    findings = _findings_list(findings)
    if not findings:
        return "audit_context: clean (no forward-reference leaks)"
    return f"audit_context: {len(findings)} leak(s) found"
