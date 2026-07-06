"""Gate whether a replay artifact completed without recorded errors.

``acceptance`` and ``promotion`` embed error checks inside broader criteria. ``check_run_clean``
is a minimal pass/fail gate for the common CI question: did this run finish without an
``error`` on the artifact, its generalization partitions, or any ``per_repo`` row?

The companion ``scripts/run_clean.py`` exits non-zero when errors are present.

Pure evaluation: no I/O, never mutates the result, and a malformed/non-dict result fails closed.
"""

from __future__ import annotations

import logging

from benchmark.comparability import artifact_kind

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "run_clean: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _partition_errors(artifact: dict) -> list[str]:
    findings = []
    if artifact.get("error"):
        findings.append(f"top-level error: {artifact.get('error')!r}")
    kind = artifact_kind(artifact)
    if kind == "generalization":
        for part in ("tuned", "held_out"):
            err = _dict(artifact.get(part)).get("error")
            if err:
                findings.append(f"{part} error: {err!r}")
        containers = [
            ("tuned", _dict(artifact.get("tuned")).get("per_repo")),
            ("held_out", _dict(artifact.get("held_out")).get("per_repo")),
        ]
    elif kind == "multi":
        containers = [("multi", artifact.get("per_repo"))]
    else:
        return findings
    for label, per_repo in containers:
        if not isinstance(per_repo, list):
            continue
        for idx, entry in enumerate(per_repo):
            if isinstance(entry, dict) and entry.get("error"):
                repo = entry.get("repo") or entry.get("repo_name") or idx
                findings.append(f"{label}.per_repo[{repo}] error: {entry.get('error')!r}")
    return findings


def check_run_clean(result) -> dict:
    """Evaluate whether ``result`` completed without recorded errors."""
    if not isinstance(result, dict):
        findings = ["artifact is not a JSON object"]
        kind = "invalid"
    else:
        findings = _partition_errors(result)
        kind = artifact_kind(result)
    checks = [{
        "name": "no_errors",
        "passed": not findings,
        "detail": "no errors recorded" if not findings else "; ".join(findings),
    }]
    return {
        "passed": not findings,
        "checks": checks,
        "findings": findings,
        "artifact_kind": kind,
    }


def failed_checks(result: dict) -> list:
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def run_clean_headline(result: dict) -> str:
    result = _dict(result)
    if result.get("passed"):
        return f"run clean: OK ({result.get('artifact_kind')})"
    findings = result.get("findings") or []
    return f"run clean: ERRORS ({len(findings)} finding(s))"
