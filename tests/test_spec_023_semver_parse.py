"""Contract tests for specs/023-benchmark-semver-parse — assert score.parse_semver and
score.bump_level satisfy the spec's EARS criteria: input guards, token extraction, forward-bump
classification, and canonical BUMP_LEVELS. Offline, deterministic.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score import _BUMP_LEVELS, bump_level, parse_semver  # noqa: E402

# Spec name for the implementation constant (``score._BUMP_LEVELS``).
BUMP_LEVELS = _BUMP_LEVELS

_NON_STRING_INPUTS = [None, 42, 3.14, True, [], {}, ()]

# --- parse_semver input guard -------------------------------------------------------------


@pytest.mark.parametrize("bad", _NON_STRING_INPUTS)
def test_parse_semver_non_string_returns_none(bad):
    assert parse_semver(bad) is None


# --- parse_semver token extraction --------------------------------------------------------


def test_parse_semver_leading_v():
    assert parse_semver("v1.2.0") == (1, 2, 0)
    assert parse_semver("V2.3.4") == (2, 3, 4)
    assert parse_semver("1.2.0") == (1, 2, 0)


def test_parse_semver_missing_patch():
    assert parse_semver("1.4") == (1, 4, 0)
    assert parse_semver("v9.10") == (9, 10, 0)


def test_parse_semver_ignores_prerelease_suffix():
    assert parse_semver("v3.1.4-rc2") == (3, 1, 4)
    assert parse_semver("2.0.0+build.42") == (2, 0, 0)
    assert parse_semver("1.0.0-alpha.1+meta") == (1, 0, 0)


def test_parse_semver_no_token_returns_none():
    assert parse_semver("no version here") is None
    assert parse_semver("") is None
    assert parse_semver("   ") is None


def test_parse_semver_first_token_wins():
    # Embedded in a subject line — first semver core is extracted.
    assert parse_semver("Release v2.0.0 today") == (2, 0, 0)
    assert parse_semver("bump dep to 9.9.9 before 1.2.3") == (9, 9, 9)


# --- parse_semver output shape ------------------------------------------------------------


def test_parse_semver_returns_int_tuple():
    result = parse_semver("v1.2.3")
    assert isinstance(result, tuple)
    assert len(result) == 3
    assert all(isinstance(part, int) and part >= 0 for part in result)


def test_parse_semver_does_not_mutate_input():
    raw = "keep v1.0.0 intact"
    snapshot = raw
    parse_semver(raw)
    assert raw == snapshot


# --- bump_level input guard ---------------------------------------------------------------


@pytest.mark.parametrize("bad_old", [None, "str", [1, 2, 3], 42])
@pytest.mark.parametrize("bad_new", [None, "str", [1, 0, 0]])
def test_bump_level_non_tuple_returns_none(bad_old, bad_new):
    assert bump_level(bad_old, (2, 0, 0)) is None
    assert bump_level((1, 0, 0), bad_new) is None
    assert bump_level(bad_old, bad_new) is None


@pytest.mark.parametrize("short", [(1,), (1, 2), ()])
def test_bump_level_short_tuple_returns_none(short):
    assert bump_level(short, (1, 0, 0)) is None
    assert bump_level((1, 0, 0), short) is None


def test_bump_level_empty_tuple_returns_none():
    assert bump_level((), (1, 0, 0)) is None
    assert bump_level((1, 0, 0), ()) is None


# --- bump_level forward bump only ---------------------------------------------------------


def test_bump_level_no_change_returns_none():
    assert bump_level((1, 2, 3), (1, 2, 3)) is None


def test_bump_level_backward_returns_none():
    assert bump_level((2, 0, 0), (1, 9, 9)) is None
    assert bump_level((1, 3, 0), (1, 2, 9)) is None
    assert bump_level((1, 2, 4), (1, 2, 3)) is None


# --- bump_level classification ------------------------------------------------------------


def test_bump_level_major_minor_patch():
    assert bump_level((1, 2, 3), (2, 0, 0)) == "major"
    assert bump_level((1, 2, 3), (1, 3, 0)) == "minor"
    assert bump_level((1, 2, 3), (1, 2, 4)) == "patch"


def test_bump_level_returns_canonical_levels_only():
    cases = [
        ((0, 0, 0), (0, 0, 1), "patch"),
        ((1, 0, 0), (1, 1, 0), "minor"),
        ((3, 2, 1), (4, 0, 0), "major"),
    ]
    for old, new, expected in cases:
        result = bump_level(old, new)
        assert result == expected
        assert result in BUMP_LEVELS


def test_bump_level_patch_zero_is_legitimate_forward_bump():
    # Legitimate 0 patch component must not be confused with missing input.
    assert bump_level((1, 2, 0), (1, 2, 1)) == "patch"
    assert bump_level((1, 4, 0), (1, 5, 0)) == "minor"


def test_bump_levels_constant_matches_spec():
    assert BUMP_LEVELS == ("major", "minor", "patch")
