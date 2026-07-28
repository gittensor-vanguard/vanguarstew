"""Package a public Git replay and transcript into Polaris's eight mounted-file slots.

The package contains only a shallow bare Git database, a canonical transcript, and a small public
manifest.  It deliberately excludes the working tree: the measured image reconstructs that from
Git, saving enough space to stay within Polaris's 8 x 256 KiB input limit.
"""

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
import tempfile
from pathlib import Path

from benchmark.polaris import (
    POLARIS_INPUT_PACKAGE_VERSION,
    POLARIS_MAX_MOUNTED_FILE_BYTES,
    POLARIS_MAX_MOUNTED_FILES,
    mounted_files_sha256,
)
from benchmark.transcript import TranscriptStore, canonical_json

PACKAGE_VERSION = POLARIS_INPUT_PACKAGE_VERSION
PART_BYTES = POLARIS_MAX_MOUNTED_FILE_BYTES
MAX_PARTS = POLARIS_MAX_MOUNTED_FILES
MAX_PACKAGE_BYTES = PART_BYTES * MAX_PARTS
DEFAULT_DEPTH = 32

_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40}")
_PUBLIC_REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_GITHUB_ORIGIN_RE = re.compile(
    r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


class InputPackageError(RuntimeError):
    """A public input could not be safely represented in the Polaris file budget."""


def _git(repo: Path, *args: str, git_dir: bool = False) -> str:
    command = ["git", f"--git-dir={repo}", *args] if git_dir else ["git", "-C", str(repo), *args]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise InputPackageError("git could not prepare the public replay input") from exc
    return result.stdout.strip()


def _validate_public_source(repo: Path, public_repo: str, ref: str) -> tuple[str, str]:
    if not repo.is_dir() or not _PUBLIC_REPO_RE.fullmatch(public_repo or ""):
        raise InputPackageError("a public GitHub checkout and owner/name slug are required")
    origin = _git(repo, "remote", "get-url", "origin")
    match = _GITHUB_ORIGIN_RE.fullmatch(origin)
    if not match or match.group("slug").lower() != public_repo.lower():
        raise InputPackageError("public repository slug does not match the checkout origin")
    commit = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if not _COMMIT_RE.fullmatch(commit):
        raise InputPackageError("public repository ref did not resolve to a full commit")
    return public_repo.lower(), commit.lower()


def _normalized_tar(source: Path, manifest: bytes, transcript: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", compresslevel=9, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name, content in (("manifest.json", manifest), ("transcript.json", transcript)):
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(content))

            root_info = tarfile.TarInfo("repo.git")
            root_info.type = tarfile.DIRTYPE
            root_info.mode = 0o755
            root_info.mtime = 0
            archive.addfile(root_info)
            for path in sorted(source.rglob("*"), key=lambda item: item.as_posix()):
                relative = path.relative_to(source).as_posix()
                info = tarfile.TarInfo(f"repo.git/{relative}")
                info.mtime = 0
                if path.is_dir():
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                elif path.is_file() and not path.is_symlink():
                    info.size = path.stat().st_size
                    info.mode = 0o644
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
                else:
                    raise InputPackageError("bare repository contains an unsupported file type")
    return output.getvalue()


def _build_archive(
    repo: Path,
    public_repo: str,
    commit: str,
    depth: int,
    transcript: bytes,
) -> bytes:
    with tempfile.TemporaryDirectory(prefix="vanguarstew_package_") as temporary:
        bare = Path(temporary) / "repo.git"
        _git(Path(temporary), "init", "--quiet", "--bare", "--template=", str(bare))
        _git(bare, "remote", "add", "origin", repo.resolve().as_uri(), git_dir=True)
        _git(
            bare,
            "fetch",
            "--quiet",
            "--depth",
            str(depth),
            "origin",
            commit,
            git_dir=True,
        )
        _git(bare, "update-ref", "refs/heads/input", commit, git_dir=True)
        _git(bare, "symbolic-ref", "HEAD", "refs/heads/input", git_dir=True)
        _git(
            bare,
            "remote",
            "set-url",
            "origin",
            f"https://github.com/{public_repo}.git",
            git_dir=True,
        )
        fetch_head = bare / "FETCH_HEAD"
        if fetch_head.exists():
            fetch_head.unlink()

        manifest = canonical_json(
            {
                "version": PACKAGE_VERSION,
                "public_repo": public_repo,
                "commit": commit,
                "depth": depth,
                "transcript_sha256": hashlib.sha256(transcript).hexdigest(),
            }
        ).encode("utf-8")
        return _normalized_tar(bare, manifest, transcript)


def package_inputs(
    *,
    repo: str,
    public_repo: str,
    ref: str,
    depth: int,
    transcript_path: str,
    out_dir: str,
) -> dict:
    if depth < 16 or depth > 256:
        raise InputPackageError("history depth must be between 16 and 256 commits")
    slug, commit = _validate_public_source(Path(repo), public_repo, ref)
    try:
        store = TranscriptStore.load(transcript_path)
    except (OSError, ValueError) as exc:
        raise InputPackageError("cannot load the public replay transcript") from exc
    if not len(store):
        raise InputPackageError("public replay transcript must contain at least one response")
    transcript = canonical_json(store.to_dict()).encode("utf-8")
    archive = _build_archive(Path(repo), slug, commit, depth, transcript)
    if len(archive) > MAX_PACKAGE_BYTES:
        raise InputPackageError("public replay package exceeds Polaris's eight-file limit")

    destination = Path(out_dir)
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    except OSError as exc:
        raise InputPackageError("output directory must be a new path with an existing parent") from exc
    parts = []
    mounted_files = {}
    for index, offset in enumerate(range(0, len(archive), PART_BYTES)):
        content = archive[offset : offset + PART_BYTES]
        name = f"input.part{index:02d}"
        target = f"/submission/{name}"
        path = destination / name
        path.write_bytes(content)
        mounted_files[target] = content
        parts.append(
            {
                "name": name,
                "target": target,
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    return {
        "version": PACKAGE_VERSION,
        "public_repo": slug,
        "commit": commit,
        "depth": depth,
        "package_sha256": hashlib.sha256(archive).hexdigest(),
        "files_sha256": mounted_files_sha256(mounted_files),
        "parts": parts,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="local checkout of the public repository")
    parser.add_argument("--public-repo", required=True, help="public GitHub owner/name slug")
    parser.add_argument("--ref", default="HEAD", help="public commit/ref to package")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--transcript", required=True, help="recorded public replay transcript")
    parser.add_argument("--out-dir", required=True, help="new directory for input.partNN files")
    args = parser.parse_args(argv)
    try:
        result = package_inputs(
            repo=args.repo,
            public_repo=args.public_repo,
            ref=args.ref,
            depth=args.depth,
            transcript_path=args.transcript,
            out_dir=args.out_dir,
        )
    except Exception:
        print("attested input packaging failed", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
