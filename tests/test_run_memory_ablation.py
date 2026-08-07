"""Tests for the local source-anchored memory-ablation command."""

from __future__ import annotations

from argparse import Namespace

import pytest

from scripts import run_memory_ablation as cli


def _args(**overrides):
    values = {
        "repo": "/public/repo",
        "memory_repository_id": "owner/repo",
        "memory_store": None,
        "source_corpus_events": 400,
        "memory_items": 8,
        "agent": "agent.py",
        "tasks": 6,
        "horizon": 5,
        "min_history": 10,
        "after": None,
        "before": None,
        "horizon_days": None,
        "model": "model",
        "api_base": "https://example.invalid/v1",
        "api_key": None,
        "api_key_env": "TEST_MEMORY_ABLATION_KEY",
        "env_file": None,
        "seed": 3,
        "rotation_seed": 5,
        "single_order_judge": True,
        "min_pairs": 6,
        "min_effect": 0.05,
        "alpha": 0.05,
        "bootstrap_samples": 200,
        "bootstrap_seed": 7,
        "out": None,
    }
    values.update(overrides)
    return Namespace(**values)


def test_resolve_api_key_reads_only_the_named_environment_variable(monkeypatch):
    monkeypatch.setenv("TEST_MEMORY_ABLATION_KEY", "secret")
    assert cli.resolve_api_key(None, "TEST_MEMORY_ABLATION_KEY") == "secret"
    with pytest.raises(ValueError, match="either"):
        cli.resolve_api_key("direct", "TEST_MEMORY_ABLATION_KEY")
    with pytest.raises(ValueError, match="environment variable"):
        cli.resolve_api_key(None, "bad-name")


def test_resolve_api_key_reads_only_the_requested_literal_dotenv_value(tmp_path, monkeypatch):
    monkeypatch.delenv("TEST_MEMORY_ABLATION_KEY", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "UNRELATED=do-not-read\nexport TEST_MEMORY_ABLATION_KEY='dotenv-secret'\n",
        encoding="utf-8",
    )
    assert cli.resolve_api_key(None, "TEST_MEMORY_ABLATION_KEY", str(dotenv)) == "dotenv-secret"
    with pytest.raises(ValueError, match="requires"):
        cli.resolve_api_key(None, None, str(dotenv))
    with pytest.raises(ValueError, match="cannot be read"):
        cli.resolve_api_key(None, "TEST_MEMORY_ABLATION_KEY", str(tmp_path / "missing"))


def test_run_builds_an_isolated_source_provider_and_passes_no_key_in_output(monkeypatch):
    monkeypatch.setenv("TEST_MEMORY_ABLATION_KEY", "secret")
    captured = {}

    class FakeStore:
        def __init__(self, path):
            captured["store_path"] = path

        def __enter__(self):
            return self

        def __exit__(self, *_unused):
            return None

    def corpus(store, **kwargs):
        captured["corpus_store"] = store
        captured["corpus_kwargs"] = kwargs
        return {"source_root": "a" * 64}

    class FakeProvider:
        def __init__(self, store, **kwargs):
            captured["provider_store"] = store
            captured["provider_kwargs"] = kwargs

    def ablation(repo, **kwargs):
        captured["repo"] = repo
        captured["ablation_kwargs"] = kwargs
        return {"paired": {"significant_improvement": False}}

    monkeypatch.setattr(cli, "MemoryStore", FakeStore)
    monkeypatch.setattr(cli, "import_source_commit_corpus", corpus)
    monkeypatch.setattr(cli, "SourceAnchoredBenchmarkProvider", FakeProvider)
    monkeypatch.setattr(cli, "run_paired_memory_ablation", ablation)

    result = cli.run(_args())

    assert captured["store_path"] == ":memory:"
    assert captured["corpus_kwargs"] == {
        "repo_path": "/public/repo", "repository_id": "owner/repo", "max_events": 400,
    }
    assert captured["provider_kwargs"] == {"repository_id": "owner/repo", "max_items": 8}
    assert captured["ablation_kwargs"]["api_key"] == "secret"
    assert captured["ablation_kwargs"]["memory_provider"] is not None
    assert "secret" not in str(result)
