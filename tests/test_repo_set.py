"""Tests for the leakage-safe repo-set config + loader (issue #55). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import (  # noqa: E402
    EXAMPLE_REPO_SET,
    RepoSetError,
    load_repo_set,
    validate_repo_set,
)

VALID = {
    "name": "t",
    "description": "d",
    "strategy": "s",
    "repos": [
        {"name": "a", "source": "https://x/a", "tier": "recent",
         "freeze_window": {"after": "2025-09-01", "recent_bias": True, "min_history": 30}},
        {"name": "b", "source": "/local/b", "tier": "obscure", "held_out": True,
         "freeze_window": {"rotation_seed": 5}},
    ],
}


def _mutate(**entry0):
    data = copy.deepcopy(VALID)
    data["repos"][0].update(entry0)
    return data


def test_shipped_example_config_loads_and_is_wellformed():
    rs = load_repo_set(EXAMPLE_REPO_SET)     # path is required; load the shipped example
    assert rs.name == "example"
    assert len(rs) >= 2
    assert len(rs.names()) == len(set(rs.names()))            # unique names
    assert all(e.tier in ("recent", "obscure") for e in rs)
    # a leakage-safe set is a mix and reserves held-out repos for generalization
    assert rs.held_out() and rs.tuned()
    assert rs.by_tier("recent") and rs.by_tier("obscure")


def test_strict_top_level_validation():
    # unknown top-level key (a typo like "reposs") is rejected, not silently ignored
    with pytest.raises(RepoSetError, match="unknown top-level keys"):
        validate_repo_set({"repos": VALID["repos"], "reposs": []})
    with pytest.raises(RepoSetError, match="unknown top-level keys"):
        validate_repo_set({**VALID, "stratergy": "typo"})
    # metadata fields must be strings when present
    for key in ("name", "description", "strategy"):
        with pytest.raises(RepoSetError, match=f"top-level '{key}' must be a string"):
            validate_repo_set({**VALID, key: 123})


def test_valid_config_partitions_and_retrieves():
    rs = validate_repo_set(VALID)
    assert rs.names() == ["a", "b"]
    assert rs.sources() == ["https://x/a", "/local/b"]
    assert [e.name for e in rs.tuned()] == ["a"]
    assert [e.name for e in rs.held_out()] == ["b"]
    assert rs.entries[0].freeze_window["recent_bias"] is True


@pytest.mark.parametrize("bad, match", [
    ({"repos": []}, "non-empty"),
    ({"repos": "nope"}, "non-empty list"),
    ({}, "non-empty list"),
    ([], "JSON object"),
])
def test_top_level_validation(bad, match):
    with pytest.raises(RepoSetError, match=match):
        validate_repo_set(bad)


def test_missing_and_bad_entry_fields():
    with pytest.raises(RepoSetError, match="'name' is required"):
        validate_repo_set(_mutate(name=""))
    with pytest.raises(RepoSetError, match="'source' is required"):
        validate_repo_set(_mutate(source=""))
    with pytest.raises(RepoSetError, match="'tier' must be one of"):
        validate_repo_set(_mutate(tier="weekly"))
    with pytest.raises(RepoSetError, match="'held_out' must be a boolean"):
        validate_repo_set(_mutate(held_out="yes"))


def test_duplicate_names_rejected():
    data = copy.deepcopy(VALID)
    data["repos"][1]["name"] = "a"
    with pytest.raises(RepoSetError, match="duplicate repo name"):
        validate_repo_set(data)


def test_freeze_window_validation():
    with pytest.raises(RepoSetError, match="unknown freeze_window key"):
        validate_repo_set(_mutate(freeze_window={"afterr": "2025-01-01"}))
    with pytest.raises(RepoSetError, match="recent_bias must be a boolean"):
        validate_repo_set(_mutate(freeze_window={"recent_bias": 1}))
    # bool is a subclass of int, but rotation_seed must be a real int
    with pytest.raises(RepoSetError, match="rotation_seed must be an integer"):
        validate_repo_set(_mutate(freeze_window={"rotation_seed": True}))


def test_unknown_entry_key_rejected():
    with pytest.raises(RepoSetError, match="unknown keys"):
        validate_repo_set(_mutate(extra="x"))


def test_load_requires_explicit_path():
    # no implicit default: a config must always be chosen on purpose
    with pytest.raises(TypeError):
        load_repo_set()


def test_load_reports_missing_file_and_bad_json(tmp_path):
    with pytest.raises(RepoSetError, match="not found"):
        load_repo_set(str(tmp_path / "nope.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(RepoSetError, match="invalid JSON"):
        load_repo_set(str(bad))


def test_example_json_is_parseable_directly():
    # sanity: the shipped file is literally valid JSON
    with open(EXAMPLE_REPO_SET, "r", encoding="utf-8") as f:
        json.load(f)
