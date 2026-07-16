"""Report the share of per-repo rows that failed with an error in a replay artifact.

A multi-repo run keeps each repository's outcome in ``per_repo``; a repo that could not be evaluated
(clone/freeze failure, too small for the horizon, an exception) carries a truthy ``error`` field. This
read-only utility reports the fraction of repos that errored, with per-partition (``tuned``/
``held_out``) detail for a ``--generalization`` artifact, so a dashboard can flag a run whose headline
was computed over only the repos that survived.

Pure analysis: no I/O, never mutates its input. The share is always a decimal fraction in ``[0, 1]``
(the headline renders it as a percentage); a slice with no countable repo yields a ``None`` share.
A single-repo run counts as one repo (its own top-level ``error``); when ``per_repo`` is present the
top-level ``error`` is ignored, so an error is never double-counted.
"""

from __future__ import annotations

from benchmark.comparability import artifact_kind


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _has_error(entry) -> bool:
    """True when a repo row carries a truthy ``error`` (a message); absent/``None``/empty is clean."""
    return bool(_dict(entry).get("error"))


def _repo_error_flags(slice_) -> list[bool]:
    """One error flag per repo in a slice.

    A multi-repo slice contributes one flag per countable entry in ``per_repo`` — a dict row
    (flagged when it carries a truthy ``error``) or a non-empty string row (a malformed/corrupt
    entry, always an error). A single-repo slice contributes its own top-level ``error`` as one
    repo. Empty/whitespace strings and other non-dict/non-string entries carry no error signal and
    are skipped. When ``per_repo`` is a list the top-level ``error`` is not counted, so a failure
    recorded in both places is counted once.
    """
    slice_ = _dict(slice_)
    per_repo = slice_.get("per_repo")
    if isinstance(per_repo, list):
        flags = []
        for entry in per_repo:
            if isinstance(entry, dict):
                flags.append(_has_error(entry))
            elif isinstance(entry, str) and entry.strip():
                # A per_repo row that is itself a non-empty string is a malformed/corrupt entry,
                # not a well-formed result dict — count it as an errored repo so the share
                # reflects the real failure rate, matching ``benchmark.acceptance._partition_error``
                # and ``check_run_clean``.
                flags.append(True)
        return flags
    return [_has_error(slice_)]


def _error_share(flags: list[bool]) -> dict:
    """``repos``/``error_repos``/``error_share`` for a list of per-repo error flags (empty → ``None``)."""
    if not flags:
        return {"repos": 0, "error_repos": 0, "error_share": None}
    errored = sum(1 for flag in flags if flag)
    return {"repos": len(flags), "error_repos": errored, "error_share": round(errored / len(flags), 3)}


def summarize_error_repo_share(artifact) -> dict:
    """Return the errored-repo share for a replay ``artifact``.

    Single- and multi-repo artifacts report a top-level share; a ``generalization`` artifact reports
    each partition's share plus an overall share across both partitions' repos. An ``invalid``
    artifact (or one with no countable repo) reports a zeroed/``None`` share.
    """
    artifact = _dict(artifact)
    kind = artifact_kind(artifact)
    if kind == "generalization":
        tuned_flags = _repo_error_flags(artifact.get("tuned"))
        held_flags = _repo_error_flags(artifact.get("held_out"))
        summary = {"kind": kind, **_error_share(tuned_flags + held_flags)}
        summary["partitions"] = {
            "tuned": _error_share(tuned_flags),
            "held_out": _error_share(held_flags),
        }
        return summary
    summary = {"kind": kind, **_error_share(_repo_error_flags(artifact))}
    summary["partitions"] = None
    return summary


def error_repo_share_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`summarize_error_repo_share` result."""
    summary = _dict(summary)
    repos = summary.get("repos")
    if not _is_int(repos) or repos == 0:
        return "error repo share: no repos"
    share = summary.get("error_share")
    share_txt = f"{share:.1%}" if _is_number(share) else "n/a"
    return f"error repo share: {share_txt} ({summary.get('error_repos')}/{repos} repos errored)"
