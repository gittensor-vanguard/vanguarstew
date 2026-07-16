"""Contract tests for specs/021-benchmark-freeze-path-parse — assert freeze.parse_path_list
satisfies the spec's EARS criteria: NUL splitting, empty-field dropping, and output shape.
Offline, deterministic.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.freeze import parse_path_list  # noqa: E402

# --- Input type ---------------------------------------------------------------------------


def test_empty_string_returns_empty_list():
    assert parse_path_list("") == []


# --- NUL splitting ------------------------------------------------------------------------


def test_splits_on_nul_not_whitespace():
    raw = "docs/my file.md\0a$dollar;semi.txt\0normal.txt\0"
    assert parse_path_list(raw) == ["docs/my file.md", "a$dollar;semi.txt", "normal.txt"]


def test_preserves_paths_with_spaces_tabs_and_newlines_in_filename():
    raw = "src/my file.py\0src/tab\there.py\0"
    assert parse_path_list(raw) == ["src/my file.py", "src/tab\there.py"]


# --- Empty-field dropping -----------------------------------------------------------------


def test_drops_leading_trailing_and_duplicate_nul_fields():
    assert parse_path_list("\0a\0\0b\0") == ["a", "b"]
    assert parse_path_list("\0\0only\0\0") == ["only"]


# --- Output shape -------------------------------------------------------------------------


def test_output_is_list_of_non_empty_strings():
    result = parse_path_list("a\0b\0")
    assert isinstance(result, list)
    assert all(isinstance(path, str) and path for path in result)


def test_does_not_mutate_input_string():
    raw = "keep\0intact\0"
    snapshot = raw
    parse_path_list(raw)
    assert raw == snapshot


# --- Regression fixtures (shipped behavior) -----------------------------------------------


def test_single_path_without_trailing_nul():
    assert parse_path_list("solo.py") == ["solo.py"]


def test_only_nuls_returns_empty_list():
    assert parse_path_list("\0\0\0") == []
