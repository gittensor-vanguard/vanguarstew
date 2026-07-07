"""Tests for shared release-tag window helpers."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.releases import context_releases  # noqa: E402
from benchmark.score import base_from_releases  # noqa: E402


def test_context_releases_keeps_recent_window_when_highest_is_inside():
    tags = [f"v1.{i}.0" for i in range(1, 13)]
    releases = context_releases(tags)
    assert [r["tag"] for r in releases] == tags[-10:]


def test_context_releases_includes_highest_semver_outside_window():
    tags = ["v2.0.0", *[f"v1.{i}.0" for i in range(9, 19)]]
    releases = context_releases(tags)
    release_tags = [r["tag"] for r in releases]
    assert "v2.0.0" in release_tags
    assert base_from_releases(releases) == "v2.0.0"
    assert release_tags == [t for t in tags if t in set(release_tags)]
