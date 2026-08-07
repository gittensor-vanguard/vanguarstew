"""Tests for the model-free local coverage command."""

from __future__ import annotations

from argparse import Namespace

from scripts import run_memory_coverage as cli


def test_run_uses_an_isolated_source_provider(monkeypatch):
    captured = {}

    class FakeStore:
        def __init__(self, path):
            captured["store_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *_unused):
            return None

    class FakeProvider:
        def __init__(self, store, **kwargs):
            captured["provider"] = (store, kwargs)

    monkeypatch.setattr(cli, "MemoryStore", FakeStore)
    monkeypatch.setattr(cli, "import_source_commit_corpus", lambda store, **kwargs: {
        "source_root": "a" * 64, "store": store, "kwargs": kwargs,
    })
    monkeypatch.setattr(cli, "SourceAnchoredBenchmarkProvider", FakeProvider)
    monkeypatch.setattr(cli, "run_memory_coverage", lambda repo, **kwargs: {
        "mode": "time_safe_memory_coverage", "repo": repo, "kwargs": kwargs,
    })
    args = Namespace(
        repo="/public/repo", memory_repository_id="owner/repo", memory_store=None,
        source_corpus_events=400, memory_items=4, tasks=8, horizon=5, min_history=30,
        after=None, before="2021-01-01", horizon_days=90, rotation_seed=19, out=None,
    )

    result = cli.run(args)

    assert captured["store_path"] == ":memory:"
    assert captured["provider"][1] == {"repository_id": "owner/repo", "max_items": 4}
    assert result["mode"] == "time_safe_memory_coverage"
    assert result["kwargs"]["before"] == "2021-01-01"
