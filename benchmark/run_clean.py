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


_CHECK_ROW_KEYS = ("name", "passed")


def _is_passed(value) -> bool:
    """Accept bool values (including subclasses) and numpy.bool_; reject int 0/1."""
    if isinstance(value, bool):
        return True
    # numpy scalar bool: type name is "bool_" (numpy 1.x), "bool8" (older alias),
    # or "bool" (numpy 2.x, where np.bool_ reports __name__ == "bool").
    return type(value).__name__ in ("bool_", "bool8", "bool")


def _check_row_field(key: str, value) -> bool:
    """Return whether ``value`` is usable for a check-row ``key`` in ``_CHECK_ROW_KEYS``."""
    if key == "name":
        return isinstance(value, str) and bool(value.strip())
    if key == "passed":
        return _is_passed(value)
    return False


def _check_rows_list(checks) -> list[dict]:
    """Return run-clean check rows for the failed_checks helper.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers are warned and treated as empty (never coerced). A usable row is a
    dict with every key in ``_CHECK_ROW_KEYS``: ``name`` must be a non-empty ``str`` and
    ``passed`` must be a ``bool`` (including numpy scalar booleans); anything else is skipped
    with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "run_clean: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "run_clean: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "run_clean: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        bad_key = None
        for key in _CHECK_ROW_KEYS:
            if not _check_row_field(key, row[key]):
                bad_key = key
                break
        if bad_key is not None:
            value = row[bad_key]
            if bad_key == "name":
                detail = (
                    type(value).__name__
                    if not isinstance(value, str)
                    else "empty str"
                )
                expected = "non-empty str"
            else:
                detail = type(value).__name__
                expected = "bool"
            logger.warning(
                "run_clean: checks[%s] %s is %s, not a usable %s; skipping",
                idx,
                bad_key,
                detail,
                expected,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "run_clean: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


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
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def _findings_list(findings) -> list:
    """Return the recorded findings as a list for headline purposes.

    ``None``/absent means no findings (silent). A truthy non-list value is warned and treated
    as empty rather than coerced, mirroring :func:`_check_rows_list`'s posture, so the headline
    never calls ``len()`` on a scalar. Findings are free-form strings, so list entries are
    counted as-is (there is no per-row schema to enforce).
    """
    if findings is None:
        return []
    if not isinstance(findings, list):
        logger.warning(
            "run_clean: findings is %s, not a list; treating as empty",
            type(findings).__name__,
        )
        return []
    return findings


def run_clean_headline(result: dict) -> str:
    result = _dict(result)
    if result.get("passed"):
        return f"run clean: OK ({result.get('artifact_kind')})"
    findings = _findings_list(result.get("findings"))
    return f"run clean: ERRORS ({len(findings)} finding(s))"
