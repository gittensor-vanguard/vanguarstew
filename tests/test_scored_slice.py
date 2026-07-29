"""Tests for benchmark.scored_slice — shared unscored aggregate placeholder guard."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.scored_slice import slice_reports_unscored  # noqa: E402


def test_slice_reports_unscored_when_scored_repos_is_zero():
    assert slice_reports_unscored({"scored_repos": 0, "composite_mean": 0.0}) is True
    assert slice_reports_unscored({"scored_repos": 0.0, "composite_mean": 0.0}) is True


def test_slice_reports_unscored_false_when_scored_or_missing():
    assert slice_reports_unscored({"scored_repos": 2, "composite_mean": 0.6}) is False
    assert slice_reports_unscored({"composite_mean": 0.0}) is False
    assert slice_reports_unscored(None) is False
    assert slice_reports_unscored({"scored_repos": False, "composite_mean": 0.7}) is False
