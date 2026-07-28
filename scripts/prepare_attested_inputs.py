"""Safely reconstruct a packaged public replay inside the measured eval image."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

from benchmark.polaris import (
    POLARIS_INPUT_PACKAGE_VERSION,
    POLARIS_MAX_MOUNTED_FILE_BYTES,
    POLARIS_MAX_MOUNTED_FILES,
)

PACKAGE_VERSION = POLARIS_INPUT_PACKAGE_VERSION
PART_BYTES = POLARIS_MAX_MOUNTED_FILE_BYTES
MAX_PARTS = POLARIS_MAX_MOUNTED_FILES
MAX_PACKAGE_BYTES = PART_BYTES * MAX_PARTS
MAX_EXTRACTED_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 10_000

_COMMIT_RE = re.compile(r"[0-9a-f]{40}")
_PUBLIC_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PART_RE = re.compile(r"input\.part(?P<index>0[0-7])")


class InputPreparationError(RuntimeError):
    """Mounted input parts failed integrity, archive, or public-identity checks."""


def _git(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InputPreparationError("git could not reconstruct the public replay input") from exc
    return result.stdout.strip()


def _read_parts(part_paths: list[str]) -> bytes:
    if not part_paths or len(part_paths) > MAX_PARTS:
        raise InputPreparationError("one to eight mounted package parts are required")
    chunks = []
    for index, raw_path in enumerate(part_paths):
        path = Path(raw_path)
        match = _PART_RE.fullmatch(path.name)
        if not match or int(match.group("index")) != index:
            raise InputPreparationError("mounted package parts must be consecutive and ordered")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise InputPreparationError("cannot read a mounted package part") from exc
        if not content or len(content) > PART_BYTES:
            raise InputPreparationError("mounted package part has an invalid size")
        chunks.append(content)
    archive = b"".join(chunks)
    if len(archive) > MAX_PACKAGE_BYTES:
        raise InputPreparationError("mounted package exceeds the input limit")
    return archive


def _decompress(archive: bytes) -> bytes:
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive), mode="rb") as compressed:
            content = compressed.read(MAX_EXTRACTED_BYTES + 1)
    except (OSError, EOFError) as exc:
        raise InputPreparationError("mounted package is not valid gzip data") from exc
    if len(content) > MAX_EXTRACTED_BYTES:
        raise InputPreparationError("mounted package exceeds the extracted-size limit")
    return content


def _extract_archive(archive: bytes, destination: Path) -> None:
    tar_bytes = _decompress(archive)
    try:
        bundle = tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:")
    except tarfile.TarError as exc:
        raise InputPreparationError("mounted package is not a valid tar archive") from exc
    with bundle:
        members = bundle.getmembers()
        if len(members) > MAX_MEMBERS:
            raise InputPreparationError("mounted package contains too many archive members")
        total = 0
        names = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in member.name
                or not path.parts
                or path.parts[0] not in {"manifest.json", "transcript.json", "repo.git"}
                or not (member.isdir() or member.isfile())
            ):
                raise InputPreparationError("mounted package contains an unsafe archive member")
            if member.name in names:
                raise InputPreparationError("mounted package contains a duplicate archive member")
            names.add(member.name)
            if path.parts[0] != "repo.git" and len(path.parts) != 1:
                raise InputPreparationError("mounted package contains an unexpected archive member")
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise InputPreparationError("mounted package exceeds the extracted-size limit")
        if not {"manifest.json", "transcript.json", "repo.git"}.issubset(names):
            raise InputPreparationError("mounted package is missing a required archive member")

        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = bundle.extractfile(member)
            if source is None:
                raise InputPreparationError("mounted package file could not be read")
            with target.open("wb") as handle:
                handle.write(source.read())


def prepare_inputs(
    *,
    part_paths: list[str],
    out_dir: str,
    expected_public_repo: str,
    expected_commit: str,
) -> dict:
    if not _PUBLIC_REPO_RE.fullmatch(expected_public_repo or ""):
        raise InputPreparationError("expected public repository must be an owner/name slug")
    if not _COMMIT_RE.fullmatch(expected_commit or ""):
        raise InputPreparationError("expected commit must be a lowercase full commit id")
    destination = Path(out_dir)
    if destination.exists():
        raise InputPreparationError("output directory must not already exist")
    _extract_archive(_read_parts(part_paths), destination)

    try:
        manifest_raw = (destination / "manifest.json").read_bytes()
        transcript = (destination / "transcript.json").read_bytes()
        manifest = json.loads(manifest_raw)
    except (OSError, ValueError) as exc:
        raise InputPreparationError("mounted package manifest is unreadable") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "version",
        "public_repo",
        "commit",
        "depth",
        "transcript_sha256",
    }:
        raise InputPreparationError("mounted package manifest has the wrong shape")
    checks = {
        "version": manifest.get("version") == PACKAGE_VERSION,
        "public_repo": manifest.get("public_repo") == expected_public_repo.lower(),
        "commit": manifest.get("commit") == expected_commit,
        "depth": isinstance(manifest.get("depth"), int)
        and not isinstance(manifest.get("depth"), bool)
        and 16 <= manifest["depth"] <= 256,
        "transcript": manifest.get("transcript_sha256")
        == hashlib.sha256(transcript).hexdigest(),
    }
    if not all(checks.values()):
        raise InputPreparationError("mounted package manifest does not match expected inputs")

    bare = destination / "repo.git"
    actual_commit = _git(f"--git-dir={bare}", "rev-parse", "--verify", "HEAD")
    if actual_commit != expected_commit:
        raise InputPreparationError("bare repository does not match the expected commit")
    checkout = destination / "repo"
    _git("clone", "--quiet", "--no-hardlinks", "--", str(bare), str(checkout))
    _git(
        "-C",
        str(checkout),
        "remote",
        "set-url",
        "origin",
        f"https://github.com/{expected_public_repo.lower()}.git",
    )
    return {
        "repo": str(checkout),
        "transcript": str(destination / "transcript.json"),
        "public_repo": expected_public_repo.lower(),
        "commit": expected_commit,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", action="append", required=True, help="ordered input.partNN path")
    parser.add_argument("--out-dir", default="/tmp/vanguarstew-input")
    parser.add_argument("--expected-public-repo", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        prepare_inputs(
            part_paths=args.part,
            out_dir=args.out_dir,
            expected_public_repo=args.expected_public_repo,
            expected_commit=args.expected_commit,
        )
    except Exception:
        print("attested input preparation failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
