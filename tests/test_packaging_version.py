"""Packaging metadata must track the latest release tag."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)
_SEMVER_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = _VERSION_RE.search(text)
    assert match is not None, "pyproject.toml is missing [project].version"
    return match.group(1)


def _latest_release_tag() -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "tag", "-l", "v*", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        pytest.skip("git tags unavailable in this checkout")
    tags = [line.strip() for line in out.stdout.splitlines() if line.strip()]
    if not tags:
        pytest.skip("no release tags in this checkout (shallow clone or export)")
    return tags[0]


def test_pyproject_version_is_well_formed_semver():
    version = _pyproject_version()
    assert _SEMVER_RE.match(version), (
        f"pyproject.toml version {version!r} is not well-formed semver"
    )


def test_pyproject_version_matches_latest_release_tag():
    packaged = _pyproject_version()
    latest = _latest_release_tag().removeprefix("v")
    assert packaged == latest, (
        f"pyproject.toml version {packaged!r} does not match latest release tag v{latest}"
    )
