"""Tests for the isolated public source-anchored benchmark corpus."""

from __future__ import annotations

import os
import subprocess

import pytest

from benchmark.memory import MemoryStore
from benchmark.runner import run_replay
from benchmark.source_memory import (
    SourceAnchoredBenchmarkProvider,
    SourceCorpusError,
    _changed_paths,
    import_source_commit_corpus,
    source_memory_query,
)


def _history_repo(path, commits: int = 16):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    for index in range(commits):
        (path / f"feature_{index}.py").write_text(f"value = {index}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
        timestamp = f"{946684800 + index * 86400} +0000"
        env = {**os.environ, "GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp}
        subprocess.run(
            ["git", "-C", str(path), "commit", "-q", "-m", f"release history feature {index}"],
            check=True,
            env=env,
        )
    return path


def test_source_corpus_is_isolated_bounded_and_provenance_anchored(tmp_path):
    repo = _history_repo(tmp_path / "repo")
    with MemoryStore(tmp_path / "source.sqlite") as store:
        manifest = import_source_commit_corpus(
            store, repo_path=str(repo), repository_id="example/repo", max_events=6,
        )
        assert manifest["source_event_count"] == 6
        assert len(manifest["source_root"]) == 64
        assert store.event_count() == 6

        provider = SourceAnchoredBenchmarkProvider(store, repository_id="example/repo")
        context = {
            "frozen_at": {"date": "2000-01-11T00:00:00+00:00"},
            "recent_commits": [{"subject": "release history feature 10"}],
            "readme_excerpt": "public history",
        }
        view = provider(task={}, context=context, request="plan the next release", task_index=0)

    assert view["mode"] == "benchmark"
    assert view["boundary"]["public_only"] is True
    assert all(item["created_at"] <= 947548800 for item in view["items"])
    assert all(item["creation_method"] == "source_anchored_import" for item in view["items"])
    assert all(item["source"]["type"] == "git_commit" for item in view["items"])
    assert all('"changed_paths"' in item["evidence"] for item in view["items"])
    assert all('"action_kind"' in item["evidence"] for item in view["items"])


def test_source_corpus_rejects_a_store_with_unrelated_controller_state(tmp_path):
    repo = _history_repo(tmp_path / "repo")
    with MemoryStore(tmp_path / "source.sqlite") as store:
        store.validate(
            repository_id="example/repo",
            runtime_role="maintainer",
            kind="decision",
            structured_content={"fact": "unrelated"},
            source_type="commit",
            source_reference="commit:abc",
            source_commit="abc",
            authority="maintainer",
            observed_at=1,
            created_at=1,
        )
        with pytest.raises(SourceCorpusError, match="isolated empty"):
            import_source_commit_corpus(store, repo_path=str(repo), repository_id="example/repo")


def test_source_memory_query_uses_only_frozen_context_and_request():
    query = source_memory_query(
        {
            "recent_commits": [{"subject": "fix release timing"}],
            "readme_excerpt": "stable maintenance policy",
        },
        "plan the next maintainer action",
    )
    assert "timing" in query
    assert "stable maintenance policy" not in query
    assert "plan the next maintainer action" not in query


def test_source_provider_returns_an_empty_view_without_repository_specific_overlap(tmp_path):
    repo = _history_repo(tmp_path / "repo")
    with MemoryStore(tmp_path / "source.sqlite") as store:
        import_source_commit_corpus(store, repo_path=str(repo), repository_id="example/repo")
        provider = SourceAnchoredBenchmarkProvider(store, repository_id="example/repo")
        view = provider(
            task={},
            context={
                "frozen_at": {"date": "2000-01-11T00:00:00+00:00"},
                "recent_commits": [{"subject": "unmatched-unique-signal"}],
            },
            request="plan the next maintainer action",
            task_index=0,
        )
    assert view["items"] == []


def test_source_changed_path_import_is_batched_and_bounded(tmp_path, monkeypatch):
    repo = _history_repo(tmp_path / "repo", commits=3)
    calls = []
    import benchmark.source_memory as source_memory

    real_git = source_memory._git

    def spy(repo_path, *args):
        calls.append(args)
        return real_git(repo_path, *args)

    monkeypatch.setattr(source_memory, "_git", spy)
    shas = [
        line.strip() for line in subprocess.check_output(
            ["git", "-C", str(repo), "rev-list", "--reverse", "HEAD"], text=True,
        ).splitlines()
    ]
    result = _changed_paths(str(repo), shas)

    assert set(result) == set(shas)
    assert all(paths == [f"feature_{index}.py"] for index, paths in enumerate(result.values()))
    assert len(calls) == 1
    assert "--no-walk=unsorted" in calls[0]


def test_source_provider_integrates_with_replay_without_emitting_source_text(tmp_path):
    repo = _history_repo(tmp_path / "repo")
    with MemoryStore(tmp_path / "source.sqlite") as store:
        import_source_commit_corpus(store, repo_path=str(repo), repository_id="example/repo")
        result = run_replay(
            str(repo),
            solve_fn=lambda **_kwargs: {"philosophy": {}, "plan": [], "rationale": ""},
            memory_provider=SourceAnchoredBenchmarkProvider(store, repository_id="example/repo"),
            n_tasks=1,
            horizon=2,
            min_history=10,
            seed=0,
        )
    assert "memory_commitment" in result
    assert "release history feature" not in str(result)
