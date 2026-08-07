"""Deterministic public-source corpus for memory ablations.

This is not a way to backdate controller opinions. It imports only bounded public first-parent
commit metadata (subject, normalized action class, and changed paths), with the original commit
SHA and committer timestamp, from a repository under test. The controller can therefore
reconstruct a historical retrieval corpus later while still proving that every recalled item was
source-available at a task's freeze time. The importer never uses an LLM, contributor identity,
diff body, or future task outcomes.

The feature is intentionally for benchmark ablations.  Production live memory remains controller
validated; a source-anchored corpus is labelled by ``creation_method`` and should never be
presented as a contemporaneously recorded maintainer decision.
"""

from __future__ import annotations

import re
import subprocess

from benchmark.memory import (
    BenchmarkMemoryProvider,
    MemoryBoundaryError,
    MemoryError,
    MemoryStore,
    _bound,
    canonical_json,
    digest,
)

SOURCE_CORPUS_VERSION = 3
SOURCE_IMPORT_METHOD = "source_anchored_import"
SOURCE_IMPORT_VERSION = "source-import-v3"
MAX_SOURCE_PATHS = 16
MAX_SOURCE_PATH_CHARS = 160
_QUERY_STOPWORDS = frozenset({
    "add", "and", "bug", "build", "change", "chore", "commit", "docs", "feature",
    "fix", "for", "from", "maintainer", "next", "plan", "release", "the", "this",
    "update", "with", "work",
})
_QUERY_TOKEN = re.compile(r"[a-z0-9][a-z0-9_.-]{2,}", re.I)

_CC_KIND = {
    "feat": "feature", "feature": "feature",
    "fix": "bugfix", "bugfix": "bugfix", "bug": "bugfix",
    "docs": "docs", "doc": "docs", "refactor": "refactor",
    "release": "release", "chore": "dep", "deps": "dep", "dep": "dep",
    "build": "build", "ci": "ci", "test": "test", "tests": "test",
    "perf": "perf", "style": "style", "revert": "revert",
}
_CC_PREFIX = re.compile(r"^\s*([a-z]+)(?:\([^)]*\))?!?:", re.I)


class SourceCorpusError(MemoryError):
    """The source-anchored corpus was malformed or could not be verified."""


def _git(repo_path: str, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", repo_path, *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SourceCorpusError("cannot read the public source repository") from exc
    return result.stdout


def _history(repo_path: str) -> list[tuple[str, int, str]]:
    raw = _git(repo_path, "log", "--first-parent", "--reverse", "--format=%H%x09%ct%x09%s", "HEAD")
    history = []
    for line in raw.splitlines():
        sha, timestamp, subject = line.split("\t", 2) if line.count("\t") >= 2 else ("", "", "")
        if len(sha) != 40 or not sha.isascii() or not all(char in "0123456789abcdef" for char in sha):
            raise SourceCorpusError("source history has an invalid commit identifier")
        if not timestamp.isdigit() or int(timestamp) < 0:
            raise SourceCorpusError("source history has an invalid commit timestamp")
        history.append((sha, int(timestamp), subject))
    if not history:
        raise SourceCorpusError("source repository has no first-parent history")
    return history


def _action_kind(subject: str) -> str | None:
    """Normalize a public Conventional-Commit type without interpreting its body."""
    match = _CC_PREFIX.match(subject)
    return _CC_KIND.get(match.group(1).lower()) if match else None


def _changed_paths(repo_path: str, shas: list[str]) -> dict[str, list[str]]:
    """Read bounded public path metadata for selected commits in one Git invocation.

    A subprocess per event made corpus setup scale linearly with a large process-spawn cost. Git
    accepts the selected commits in one no-walk invocation; the record separator is inserted by
    our own format string before every full SHA and each path remains NUL-delimited. No diff body
    is requested or read.
    """
    if not shas:
        return {}
    raw = _git(
        repo_path, "show", "--no-walk=unsorted", "--format=%x1e%H%x00", "--name-only", "-z",
        "-m", "--first-parent", *shas,
    )
    result: dict[str, list[str]] = {}
    for record in raw.split("\x1e"):
        if not record:
            continue
        sha, separator, raw_paths = record.partition("\0")
        if not separator or sha not in shas:
            raise SourceCorpusError("source path metadata did not match selected commits")
        paths = []
        seen = set()
        for path in raw_paths.lstrip("\0\n").split("\0"):
            if not path or path in seen:
                continue
            seen.add(path)
            paths.append(path[:MAX_SOURCE_PATH_CHARS])
            if len(paths) >= MAX_SOURCE_PATHS:
                break
        result[sha] = paths
    if set(result) != set(shas):
        raise SourceCorpusError("source path metadata is incomplete")
    return result


def _evenly_spaced(history: list[tuple[str, int, str]], maximum: int) -> list[tuple[str, int, str]]:
    if len(history) <= maximum:
        return history
    if maximum == 1:
        return [history[-1]]
    positions = [round(index * (len(history) - 1) / (maximum - 1)) for index in range(maximum)]
    selected = [history[index] for index in positions]
    if len({row[0] for row in selected}) != len(selected):
        raise SourceCorpusError("source corpus selection is not unique")
    return selected


def import_source_commit_corpus(store: MemoryStore, *, repo_path: str, repository_id: str,
                                runtime_role: str = "maintainer", max_events: int = 400) -> dict:
    """Import a bounded, deterministic public commit-subject corpus into a fresh store.

    ``observed_at`` and ``created_at`` describe when the imported *source fact* existed, not
    when this controller reconstructed it.  ``creation_method`` makes that distinction explicit.
    Snapshot filtering still requires both timestamps to be at or before a task freeze, while the
    SHA/reference lets a verifier reproduce every item from the public source history.
    """
    if not isinstance(store, MemoryStore):
        raise SourceCorpusError("source corpus requires a controller memory store")
    if store.event_count():
        raise SourceCorpusError("source corpus requires an isolated empty controller store")
    max_events = _bound(max_events, minimum=1, maximum=500, field="source corpus max_events")
    selected = _evenly_spaced(_history(repo_path), max_events)
    selected_paths = _changed_paths(repo_path, [sha for sha, _timestamp, _subject in selected])
    event_hashes = []
    for sha, timestamp, subject in selected:
        event = store.validate(
            repository_id=repository_id,
            runtime_role=runtime_role,
            kind="source_commit_subject",
            structured_content={
                "evidence_type": "public_first_parent_commit_trajectory_metadata",
                "subject": subject[:512],
                "action_kind": _action_kind(subject),
                "changed_paths": selected_paths[sha],
            },
            source_type="git_commit",
            source_reference=f"commit:{sha}",
            source_commit=sha,
            authority="repository",
            observed_at=timestamp,
            created_at=timestamp,
            confidence=1.0,
            creation_method=SOURCE_IMPORT_METHOD,
            agent_version=SOURCE_IMPORT_VERSION,
            publication="publishable",
            recall_eligibility="evidence_only",
        )
        event_hashes.append(event["event_hash"])
    return {
        "version": SOURCE_CORPUS_VERSION,
        "repository_id": repository_id,
        "runtime_role": runtime_role,
        "source_event_count": len(event_hashes),
        "selection": "evenly_spaced_first_parent_commit_metadata",
        "source_root": digest({
            "version": SOURCE_CORPUS_VERSION,
            "repository_id": repository_id,
            "runtime_role": runtime_role,
            "event_hashes": event_hashes,
        }),
    }


def source_memory_query(context: dict, request: str, *, limit: int = 4096) -> str:
    """Build a relevance-gated query entirely from frozen recent-history terms.

    The task request is validated because it is part of the provider contract, but generic
    planning wording is deliberately not used as retrieval evidence. A recall is useful only
    when it is linked to repository-specific frozen history; otherwise the provider returns an
    empty view instead of crowding the agent prompt with broad historical noise.
    """
    if not isinstance(context, dict):
        raise MemoryBoundaryError("source memory requires a frozen context object")
    if not isinstance(request, str):
        raise MemoryBoundaryError("source memory requires a text request")
    terms = []
    commits = context.get("recent_commits")
    if isinstance(commits, list):
        for item in commits[:20]:
            if isinstance(item, dict) and isinstance(item.get("subject"), str):
                terms.extend(
                    token.lower() for token in _QUERY_TOKEN.findall(item["subject"])
                    if token.lower() not in _QUERY_STOPWORDS
                )
    # Canonicalize the exact query input so list iteration and JSON whitespace cannot perturb
    # the committed view. No content outside the frozen context is consulted here.
    rendered = canonical_json(sorted(set(terms)))
    return rendered[:limit]


class SourceAnchoredBenchmarkProvider(BenchmarkMemoryProvider):
    """Benchmark provider that retrieves source-anchored evidence using frozen context terms."""

    def __call__(self, *, task, context: dict, request: str, task_index: int) -> dict:
        return super().__call__(
            task=task,
            context=context,
            request=source_memory_query(context, request),
            task_index=task_index,
        )
