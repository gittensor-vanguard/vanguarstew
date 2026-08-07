"""Tests for aggregate-only, time-safe memory coverage diagnostics."""

from __future__ import annotations

from benchmark.memory import MemoryStore, build_memory_view
from benchmark.memory_coverage import memory_module_coverage


def _view(store):
    store.validate(
        repository_id="repo-a", runtime_role="maintainer", kind="source_commit_metadata",
        structured_content={"changed_paths": ["src/parser.py", "docs/guide.md"]},
        source_type="git_commit", source_reference="commit:abc", source_commit="abc",
        authority="repository", observed_at=100, created_at=100, publication="publishable",
        creation_method="source_anchored_import", agent_version="test",
    )
    snapshot = store.snapshot(
        repository_id="repo-a", runtime_role="maintainer", frozen_at=200, public_only=True,
    )
    return build_memory_view(
        mode="benchmark", repository_id="repo-a", runtime_role="maintainer", query="parser",
        snapshot=snapshot, frozen_at=200, public_only=True,
    )


def test_memory_module_coverage_is_aggregate_only_and_does_not_leak_paths(tmp_path):
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        result = memory_module_coverage(_view(store), [
            {"files": ["src/loader.py", "tests/test_loader.py", "README.md"]},
        ])
    assert result == {
        "actual_module_count": 3,
        "recalled_module_count": 2,
        "matched_module_count": 1,
        "module_coverage": 0.333333,
    }
    assert "parser.py" not in str(result)
    assert "loader.py" not in str(result)


def test_memory_module_coverage_rejects_a_malformed_view():
    from benchmark.memory_coverage import MemoryCoverageError

    try:
        memory_module_coverage({}, [])
    except MemoryCoverageError:
        pass
    else:
        raise AssertionError("malformed view must fail closed")
