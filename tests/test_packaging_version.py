"""Packaging metadata must track the latest release tag."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    assert match is not None, "pyproject.toml is missing [project].version"
    return match.group(1)


def _latest_release_tag() -> str:
    out = subprocess.check_output(
        ["git", "-C", str(ROOT), "tag", "-l", "v*", "--sort=-v:refname"],
        text=True,
    )
    tags = [line.strip() for line in out.splitlines() if line.strip()]
    assert tags, "expected at least one v* release tag"
    return tags[0]


def test_pyproject_version_matches_latest_release_tag():
    packaged = _pyproject_version()
    latest = _latest_release_tag().removeprefix("v")
    assert packaged == latest, (
        f"pyproject.toml version {packaged!r} does not match latest release tag v{latest}"
    )
