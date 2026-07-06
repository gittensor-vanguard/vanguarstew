"""Report the error-repo share from a replay artifact's per-repo rows.

``skip_share`` reads the multi-repo accounting fields (``repos`` / ``scored_repos``); this
read-only utility counts ``per_repo`` rows that recorded a repo-level ``error``, with
per-partition detail for a ``--generalization`` artifact.

Pure analysis: no I/O, never mutates its input. Malformed ``per_repo`` containers are skipped
rather than raising.
"""

from __future__ import annotations

import math

from benchmark.comparability import artifact_kind


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    """True only for a finite, non-boolean real number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError):  # pragma: no cover - defensive, isinstance already narrows
        return False


def _repo_rows(per_repo) -> list[dict]:
    if not isinstance(per_repo, list):
        return []
    return [entry for entry in per_repo if isinstance(entry, dict)]


def _slice_summary(slice_) -> dict:
    """``repos_total``/``repos_error``/``error_share`` for one replay slice."""
    slice_ = _dict(slice_)
    per_repo = slice_.get("per_repo")
    if per_repo is None and "error" in slice_:
        total = 1
        errors = 1 if slice_.get("error") is not None else 0
        return {
            "repos_total": total,
            "repos_error": errors,
            "error_share": float(errors),
        }
    rows = _repo_rows(per_repo)
    total = len(rows)
    if total == 0:
        return {"repos_total": 0, "repos_error": 0, "error_share": None}
    errors = sum(1 for row in rows if row.get("error") is not None)
    return {
        "repos_total": total,
        "repos_error": errors,
        "error_share": round(errors / total, 3),
    }


def summarize_error_repo_share(artifact) -> dict:
    """Return error-repo share for a replay ``artifact``."""
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned = _slice_summary(artifact.get("tuned"))
        held = _slice_summary(artifact.get("held_out"))
        total = tuned["repos_total"] + held["repos_total"]
        errors = tuned["repos_error"] + held["repos_error"]
        overall = {
            "repos_total": total,
            "repos_error": errors,
            "error_share": round(errors / total, 3) if total > 0 else None,
        }
        return {
            "kind": kind,
            **overall,
            "partitions": {"tuned": tuned, "held_out": held},
        }
    summary = {"kind": kind, **_slice_summary(artifact)}
    summary["partitions"] = None
    return summary


def error_repo_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_error_repo_share` result."""
    summary = _dict(summary)
    total = summary.get("repos_total")
    if not _is_int(total) or total == 0:
        return "error repo share: no per-repo rows"
    share = summary.get("error_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    errors = summary.get("repos_error")
    errors_txt = str(errors) if _is_int(errors) else "n/a"
    return f"error repo share: {share_txt} ({errors_txt}/{total} repo(s))"
