"""The packaging version must track the releases actually cut (#2142).

``pyproject.toml`` sat at 0.3.0 while v0.5.0 through v0.8.0 were tagged, so anything built
or installed from the tree reported a version five releases stale. These tests pin the
invariant that let that drift: the declared version is well-formed, and — whenever the
checkout carries tags — it matches the highest release tag.

The tag comparison skips rather than fails when tags are unavailable (a shallow CI clone,
an export, a source tarball), so it guards the repository without making the suite depend
on clone depth. ``tomllib`` is 3.11+ and this project supports 3.10, so the version is read
with a plain regex rather than a TOML parser.
"""

import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PYPROJECT = os.path.join(ROOT, "pyproject.toml")

# `version = "1.2.3"` in the `[project]` table. Anchored to the line start so a version
# pinned inside a dependency specifier elsewhere in the file cannot be picked up instead.
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.M)
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+)$")


def _declared_version() -> str:
    with open(PYPROJECT, encoding="utf-8") as f:
        match = _VERSION_RE.search(f.read())
    assert match, "pyproject.toml declares no project version"
    return match.group(1)


def _release_tags() -> list:
    """Semver release tags as (major, minor, patch) tuples, or [] when unavailable."""
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "tag"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    versions = []
    for line in out.stdout.split("\n"):
        match = _TAG_RE.match(line.strip())
        if match:
            versions.append(tuple(int(p) for p in match.group(1).split(".")))
    return versions


def test_declared_version_is_semver():
    version = _declared_version()
    assert _SEMVER_RE.match(version), f"pyproject version {version!r} is not major.minor.patch"


def test_declared_version_matches_the_highest_release_tag():
    tags = _release_tags()
    if not tags:
        pytest.skip("no release tags in this checkout (shallow clone or export)")
    declared = tuple(int(p) for p in _declared_version().split("."))
    highest = max(tags)
    assert declared == highest, (
        f"pyproject version {declared} does not match the highest release tag {highest}; "
        "bump the packaging version when cutting a tag"
    )
