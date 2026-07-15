"""Contract tests for specs/060-benchmark-error-repo-share — assert error_repo_share.py
satisfies the spec's EARS criteria, including malformed per_repo rows, empty slices,
non-dict artifacts, headline branches, and pure evaluation. Offline, deterministic.
"""

import copy
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.error_repo_share import (  # noqa: E402
    _dict,
    _error_share,
    _has_error,
    _is_int,
    _is_number,
    _repo_error_flags,
    error_repo_share_headline,
    summarize_error_repo_share,
)

_REQUIRED_KEYS = frozenset({"kind", "repos", "error_repos", "error_share", "partitions"})


def _ok(**extra):
    return {"composite_mean": 0.6, "tasks": 5, **extra}


def _err(msg="boom", **extra):
    return {"error": msg, "tasks": 0, **extra}


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_artifact_coerced_to_empty_dict(bad):
    # Coerced to {} → invalid kind; single-repo path still yields one clean synthetic row.
    out = summarize_error_repo_share(bad)
    assert out["kind"] == "invalid"
    assert out["partitions"] is None
    assert out["repos"] == 1
    assert out["error_repos"] == 0
    assert out["error_share"] == 0.0


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict("x") == {}


def test_is_int_and_is_number_semantics():
    assert _is_int(0)
    assert _is_int(2)
    assert not _is_int(True)
    assert not _is_int(1.0)
    assert _is_number(0.5)
    assert _is_number(1)
    assert not _is_number(True)
    assert not _is_number(None)


# --- Error detection ------------------------------------------------------------------------


def test_has_error_truthy_absent_and_non_dict():
    assert _has_error({"error": "x"}) is True
    assert _has_error({"error": ""}) is False
    assert _has_error({"error": None}) is False
    assert _has_error({}) is False
    assert _has_error("not a dict") is False
    assert _has_error(None) is False


# --- Per-repo flags -------------------------------------------------------------------------


def test_repo_error_flags_dict_and_string_rows():
    assert _repo_error_flags({"per_repo": [_ok(), _err()]}) == [False, True]
    assert _repo_error_flags({"per_repo": [_ok(), "corrupt row"]}) == [False, True]
    assert _repo_error_flags({"error": "x"}) == [True]


def test_repo_error_flags_skips_non_countable():
    flags = _repo_error_flags({"per_repo": [_err(), 5, None, "", "   ", _ok()]})
    assert flags == [True, False]


def test_per_repo_list_does_not_double_count_top_level_error():
    flags = _repo_error_flags({"error": "top-level boom", "per_repo": [_ok(), _ok()]})
    assert flags == [False, False]


def test_empty_per_repo_yields_empty_flags():
    assert _repo_error_flags({"per_repo": []}) == []


# --- Share helper ---------------------------------------------------------------------------


def test_error_share_empty_and_populated():
    assert _error_share([]) == {"repos": 0, "error_repos": 0, "error_share": None}
    assert _error_share([True, False, False, True]) == {
        "repos": 4,
        "error_repos": 2,
        "error_share": 0.5,
    }


# --- Error repo share summary ---------------------------------------------------------------


def test_multi_share():
    out = summarize_error_repo_share({"per_repo": [_ok(), _err(), _ok(), _err()]})
    assert out["kind"] == "multi"
    assert out["repos"] == 4
    assert out["error_repos"] == 2
    assert out["error_share"] == 0.5
    assert out["partitions"] is None


def test_generalization_partitions():
    out = summarize_error_repo_share({
        "generalization_gap": 0.05,
        "tuned": {"per_repo": [_ok(), _ok()]},
        "held_out": {"per_repo": [_err(), _ok()]},
    })
    assert out["kind"] == "generalization"
    assert out["repos"] == 4
    assert out["error_repos"] == 1
    assert out["error_share"] == 0.25
    assert out["partitions"]["tuned"]["error_share"] == 0.0
    assert out["partitions"]["held_out"]["error_share"] == 0.5


def test_invalid_and_empty_slice():
    empty = summarize_error_repo_share({"per_repo": []})
    assert empty["kind"] == "multi"
    assert empty["repos"] == 0
    assert empty["error_share"] is None
    assert empty["partitions"] is None

    invalid = summarize_error_repo_share({})
    assert invalid["kind"] == "invalid"
    assert invalid["partitions"] is None
    assert invalid["repos"] == 1
    assert invalid["error_share"] == 0.0


def test_summary_always_includes_required_keys():
    for artifact in (
        {"per_repo": [_ok(), _err()]},
        {"per_repo": []},
        {"generalization_gap": 0.0, "tuned": {"per_repo": []}, "held_out": {}},
        None,
        {},
    ):
        out = summarize_error_repo_share(artifact)
        assert _REQUIRED_KEYS <= frozenset(out)


# --- Error repo share headline --------------------------------------------------------------


def test_headline_exact_format():
    out = summarize_error_repo_share({"per_repo": [_ok(), _err()]})
    assert error_repo_share_headline(out) == "error repo share: 50.0% (1/2 repos errored)"


def test_headline_no_repos():
    assert error_repo_share_headline({"repos": 0}) == "error repo share: no repos"
    assert error_repo_share_headline({}) == "error repo share: no repos"
    assert error_repo_share_headline("nope") == "error repo share: no repos"
    assert error_repo_share_headline({"repos": True}) == "error repo share: no repos"


def test_headline_n_a_share():
    assert "n/a" in error_repo_share_headline({
        "repos": 2,
        "error_repos": 0,
        "error_share": None,
    })


# --- Pure evaluation ------------------------------------------------------------------------


def test_summarize_does_not_mutate_artifact():
    art = {"per_repo": [_ok(), _err()], "error": "ignored-when-per_repo"}
    snapshot = copy.deepcopy(art)
    summarize_error_repo_share(art)
    assert art == snapshot
    assert "error" in art  # input keys preserved
