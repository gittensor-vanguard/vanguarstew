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
    CURATED_REPO_SET,
    EXAMPLE_REPO_SET,
    RepoSetError,
    is_placeholder_source,
    load_repo_set,
    replay_kwargs,
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
    # a leakage-safe set reserves held-out repos for generalization, and (since 2026-07-16)
    # is all-obscure with pre-2021 windows: obscurity defends memorization, and a pre-LLM
    # bound keeps the predicted maintainer decisions human. `recent` remains a legal tier
    # value, but the set no longer requires one (see repo_set_readiness.pre_llm_windows).
    assert rs.held_out() and rs.tuned()
    assert rs.by_tier("obscure")
    assert all(e.freeze_window.get("before", "") <= "2021-01-01" for e in rs)


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


@pytest.mark.parametrize("bad_fw, match", [
    ({"min_history": 0}, "min_history must be >= 1"),
    ({"min_history": -3}, "min_history must be >= 1"),
    ({"after": ""}, "after must be non-empty"),
    ({"before": "   "}, "before must be non-empty"),
    # Non-empty but unparseable date bounds pass the string check yet crash task generation
    # with an opaque ValueError; reject them at load time with a clear message instead.
    ({"after": "not-a-date"}, "after must be an ISO date"),
    ({"before": "2023-13-01"}, "before must be an ISO date"),   # month 13 -> invalid
    ({"after": "01/02/2023"}, "after must be an ISO date"),      # non-ISO format
])
def test_freeze_window_value_validation(bad_fw, match):
    with pytest.raises(RepoSetError, match=match):
        validate_repo_set(_mutate(freeze_window=bad_fw))


def test_freeze_window_accepts_valid_iso_date_bounds():
    # A well-formed ISO date (optionally with a time suffix taskgen truncates) still loads.
    rs = validate_repo_set(_mutate(freeze_window={"after": "2023-01-01", "before": "2024-12-31"}))
    assert rs.entries[0].freeze_window["after"] == "2023-01-01"
    assert validate_repo_set(_mutate(freeze_window={"after": "2023-06-15T00:00:00Z"}))


def test_freeze_window_rejects_reversed_date_bounds():
    # after later than before => an empty window => the repo silently produces zero tasks and
    # is dropped from the curated set. Reject the reversed bounds at load time instead.
    with pytest.raises(RepoSetError, match="must be on or before"):
        validate_repo_set(_mutate(freeze_window={"after": "2024-01-01", "before": "2023-01-01"}))
    # Equal bounds are a valid (single-day) window and must still load.
    assert validate_repo_set(_mutate(freeze_window={"after": "2023-05-01", "before": "2023-05-01"}))


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


def test_load_reports_a_directory_path_as_a_clean_error(tmp_path):
    # os.path.exists is true for a directory, so a directory path reaches open() and raises
    # IsADirectoryError — an OSError, but NOT a FileNotFoundError. It must surface as a clean
    # RepoSetError carrying the real OS text, distinct from "not found" (the path DOES exist)
    # and "invalid JSON" (it was never read as text) (#1072).
    sub = tmp_path / "a_dir"
    sub.mkdir()
    with pytest.raises(RepoSetError, match="cannot read repo-set config") as exc:
        load_repo_set(str(sub))
    assert "not found" not in str(exc.value) and "invalid JSON" not in str(exc.value)


def test_load_distinguishes_not_found_directory_and_bad_json(tmp_path):
    # The three failure modes stay three distinct messages — proving the OSError branch does not
    # swallow the not-found case (FileNotFoundError is an OSError subclass, caught first).
    missing = tmp_path / "gone.json"
    a_dir = tmp_path / "dir"
    a_dir.mkdir()
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    messages = {}
    for label, path in (("missing", missing), ("dir", a_dir), ("bad", bad)):
        with pytest.raises(RepoSetError) as exc:
            load_repo_set(str(path))
        messages[label] = str(exc.value)
    assert "not found" in messages["missing"]
    assert "cannot read repo-set config" in messages["dir"]
    assert "invalid JSON" in messages["bad"]
    assert len(set(messages.values())) == 3


def test_load_reports_an_unreadable_file_as_a_clean_error(tmp_path):
    # A file that exists but is unreadable (permission denied) also reaches open(); its OSError
    # is wrapped in RepoSetError like every other load failure.
    import os
    import stat

    locked = tmp_path / "locked.json"
    locked.write_text('{"repos": []}', encoding="utf-8")
    locked.chmod(0)
    if os.access(str(locked), os.R_OK):
        # Running as root (or a filesystem that ignores mode bits): the read isn't actually
        # blocked, so there is nothing to assert. Restore and skip.
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)
        pytest.skip("cannot make a file unreadable in this environment (running as root?)")
    try:
        with pytest.raises(RepoSetError, match="cannot read repo-set config"):
            load_repo_set(str(locked))
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)  # let tmp_path cleanup remove it


def test_load_reports_a_non_utf8_file_as_a_clean_error(tmp_path):
    # A file that exists and is readable but is not valid UTF-8 (saved as UTF-16/latin-1, or a
    # binary file passed by mistake) makes json.load raise UnicodeDecodeError while decoding the
    # stream. It is a ValueError, not a JSONDecodeError or an OSError, so without a dedicated
    # branch it escapes as a raw traceback. It must surface as a clean RepoSetError, distinct from
    # "not found", "cannot read", and "invalid JSON" (#1090).
    cfg = tmp_path / "utf16.json"
    cfg.write_bytes('{"repos": []}'.encode("utf-16"))
    with pytest.raises(RepoSetError, match="is not valid UTF-8") as exc:
        load_repo_set(str(cfg))
    msg = str(exc.value)
    assert "invalid JSON" not in msg and "not found" not in msg and "cannot read" not in msg


def test_example_json_is_parseable_directly():
    # sanity: the shipped file is literally valid JSON
    with open(EXAMPLE_REPO_SET, "r", encoding="utf-8") as f:
        json.load(f)


def test_curated_config_loads_and_has_real_sources():
    rs = load_repo_set(CURATED_REPO_SET)
    assert rs.name == "curated"
    assert len(rs) >= 3
    assert all(not is_placeholder_source(e.source) for e in rs)
    assert all(e.source.startswith("https://github.com/") for e in rs)
    assert rs.tuned() and rs.held_out()
    # The set is deliberately all-obscure since 2026-07-16: memorization is defended by
    # obscurity, and every freeze window is bounded pre-2021 so the ground truth is human
    # (see benchmark/repo_set_readiness.py's pre_llm_windows check, which replaced both_tiers).
    assert rs.by_tier("obscure")
    assert all(e.freeze_window.get("before", "") <= "2021-01-01" for e in rs)


def test_partition_and_replay_kwargs():
    rs = validate_repo_set(VALID)
    assert [e.name for e in rs.partition("tuned")] == ["a"]
    assert [e.name for e in rs.partition("held_out")] == ["b"]
    assert len(rs.partition("all")) == 2
    with pytest.raises(RepoSetError, match="unknown partition"):
        rs.partition("weekly")
    assert replay_kwargs(rs.entries[0]) == {
        "recent_bias": True, "min_history": 30, "after": "2025-09-01",
    }
    assert replay_kwargs(rs.entries[1]) == {"rotation_seed": 5}
