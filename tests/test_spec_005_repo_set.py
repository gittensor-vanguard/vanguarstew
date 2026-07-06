"""Contract tests for specs/005-repo-set — assert the loader satisfies the spec's strict-loading
and freeze-window validation criteria, plus the tuned/held-out split. Deterministic, offline.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import RepoSetError, replay_kwargs, validate_repo_set  # noqa: E402


def _cfg():
    return {
        "name": "s", "description": "d", "strategy": "st",
        "repos": [
            {"name": "o/a", "source": "https://github.com/o/a", "tier": "recent",
             "freeze_window": {"after": "2023-01-01", "before": "2023-12-31",
                               "recent_bias": True, "rotation_seed": 7, "min_history": 5}},
            {"name": "o/b", "source": "https://github.com/o/b", "tier": "obscure", "held_out": True},
        ],
    }


# --- Valid config: tuned/held-out split -----------------------------------------------------

def test_valid_config_yields_tuned_held_out_split():
    rs = validate_repo_set(_cfg())
    assert [e.name for e in rs.tuned()] == ["o/a"]
    assert [e.name for e in rs.held_out()] == ["o/b"]
    assert rs.partition("all") == list(rs)
    with pytest.raises(RepoSetError):
        rs.partition("nonsense")


def test_replay_kwargs_forwards_present_hints():
    rs = validate_repo_set(_cfg())
    kw = replay_kwargs(rs.tuned()[0])
    assert kw == {"after": "2023-01-01", "before": "2023-12-31",
                  "recent_bias": True, "rotation_seed": 7, "min_history": 5}
    assert replay_kwargs(rs.held_out()[0]) == {}   # no freeze_window → no hints


# --- Strict loading -------------------------------------------------------------------------

def _expect_error(mutate):
    cfg = copy.deepcopy(_cfg())
    mutate(cfg)
    with pytest.raises(RepoSetError):
        validate_repo_set(cfg)


def test_strict_loading_rejects_malformed_top_level_and_entries():
    _expect_error(lambda c: c.__setitem__("bogus", 1))                       # unknown top-level key
    _expect_error(lambda c: c.__setitem__("repos", []))                      # empty repos
    _expect_error(lambda c: c["repos"][0].__setitem__("extra", 1))           # unknown entry key
    _expect_error(lambda c: c["repos"][0].__setitem__("name", ""))           # blank name
    _expect_error(lambda c: c["repos"][0].pop("source"))                     # missing source
    _expect_error(lambda c: c["repos"][0].__setitem__("tier", "weird"))      # bad tier
    _expect_error(lambda c: c["repos"][0].__setitem__("held_out", "yes"))    # non-bool held_out
    _expect_error(lambda c: c["repos"].append(c["repos"][0]))                # duplicate name


# --- Freeze-window validation ---------------------------------------------------------------

def _fw_error(fw):
    _expect_error(lambda c: c["repos"][0].__setitem__("freeze_window", fw))


def test_freeze_window_type_bounds_and_reversed_dates_are_rejected():
    _fw_error({"unknown_key": 1})                              # unknown hint
    _fw_error({"after": "not-a-date"})                         # unparseable ISO date
    _fw_error({"after": "2023-13-01"})                         # invalid month
    _fw_error({"after": "2023-12-31", "before": "2023-01-01"}) # reversed bounds
    _fw_error({"rotation_seed": True})                         # bool is not an int
    _fw_error({"min_history": 0})                              # must be >= 1
    _fw_error({"recent_bias": 1})                              # int is not a bool
    # A well-formed window is accepted.
    validate_repo_set(_cfg())
