"""Freeze a repo at commit T and build the leakage-safe, knowable-at-T context.

We export the working tree at T and write `.vanguarstew_context.json` alongside it, derived
only from history up to and including T (commits, tags-as-releases, README). The agent
reads that — it never sees anything after T.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile

from agent.context import CONTEXT_FILE
from benchmark.leakage import scrub_context


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def parse_path_list(out: str) -> list:
    """Parse a NUL-delimited (``git ... -z``) path list into individual paths.

    Git's ``-z`` output separates each path with a NUL byte, so filenames that
    contain spaces, tabs, newlines, or shell-sensitive characters survive intact.
    Splitting on whitespace or lines instead would corrupt such paths — and since
    benchmark scoring attributes work by file, that corruption is a hygiene bug.

    Leading/trailing NULs yield empty fields (e.g. the terminating separator), which
    we drop. Prefer this over ``str.split()``/``str.splitlines()`` for any git output
    that is a list of paths.
    """
    return [field for field in out.split("\0") if field]


def origin_url(repo: str) -> str:
    return _git(repo, "remote", "get-url", "origin", check=False).strip()


def _safe_target(dest: str, name: str) -> str:
    """Resolve a tar member ``name`` to an absolute path under ``dest``.

    Leading slashes are stripped so absolute member names are neutralized into the
    destination rather than written to the filesystem root. ``..`` traversal
    components are rejected outright. A final containment check guards against any
    residual escape.
    """
    clean = name.replace("\\", "/").lstrip("/")
    parts = [p for p in clean.split("/") if p and p != "."]
    if not parts or ".." in parts:
        raise tarfile.TarError(f"unsafe path in archive: {name!r}")
    target = os.path.abspath(os.path.join(dest, *parts))
    root = os.path.abspath(dest)
    if target != root and not target.startswith(root + os.sep):
        raise tarfile.TarError(f"path escapes destination: {name!r}")
    return target


def _safe_extractall(tf: tarfile.TarFile, dest: str) -> None:
    """Extract a git-archive tarball with a single, runtime-independent policy.

    This is applied identically on every supported Python version so a frozen tree
    never depends on whether ``tarfile.extractall(filter='data')`` happens to be
    available. The policy:

    - extracts only regular files and directories;
    - skips symlinks, hard links, and special files (devices/FIFOs) so an untrusted
      repository archive cannot plant links or escape the sandbox;
    - rejects ``..`` traversal and neutralizes absolute member paths (see
      :func:`_safe_target`);
    - writes deterministic permissions (dirs ``0o755``; files ``0o644``, plus the
      owner-execute bit git records) so the tree is byte- and mode-identical across
      runtimes and umasks.
    """
    os.makedirs(dest, exist_ok=True)
    # Iterate the archive in a single forward pass so this works on non-seekable
    # streams (``git archive | tarfile.open(mode="r|")``): each member's payload is
    # read via ``extractfile`` before advancing to the next member.
    for member in tf:
        if member.isdir():
            target = _safe_target(dest, member.name)
            os.makedirs(target, exist_ok=True)
            os.chmod(target, 0o755)
            continue
        if not member.isreg():
            # Symlinks, hard links, char/block devices, and FIFOs are never extracted.
            continue
        target = _safe_target(dest, member.name)
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            continue
        with src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        os.chmod(target, 0o755 if (member.mode & 0o100) else 0o644)


def export_tree(repo: str, commit: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.Popen(
        ["git", "-C", repo, "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
    )
    # One explicit extraction policy on all supported Python versions (3.10-3.12);
    # never delegate to the stdlib `filter='data'` path, whose availability and exact
    # behavior differ by runtime and would make frozen trees non-reproducible.
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
        _safe_extractall(tf, dest)
    proc.wait()
    if proc.returncode not in (0, None):
        raise RuntimeError(f"git archive failed for {commit}")


def file_at(repo: str, commit: str, path: str) -> str:
    r = subprocess.run(
        ["git", "-C", repo, "show", f"{commit}:{path}"],
        capture_output=True, text=True,
    )
    return r.stdout if r.returncode == 0 else ""


def build_context(repo: str, commit: str, lookback: int = 50) -> dict:
    log = _git(repo, "log", "--pretty=format:%H%x09%cI%x09%s", "-n", str(lookback), commit)
    commits = []
    for line in log.splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0][:10], "date": parts[1], "subject": parts[2]})
    # `git tag --merged` defaults to refname order, which is wrong for versions like
    # v1.10.0 vs v1.9.0. Sort by creation date so `tags[-10:]` is truly the recent window.
    tags = [
        t
        for t in _git(repo, "tag", "--sort=creatordate", "--merged", commit, check=False).splitlines()
        if t
    ]
    readme = ""
    for name in ("README.md", "README.rst", "README", "docs/README.md"):
        content = file_at(repo, commit, name)
        if content:
            readme = content[:4000]
            break
    return {
        "frozen_at": {"commit": commit[:10], "date": commits[0]["date"] if commits else None},
        "recent_commits": commits,
        "open_issues": [],   # populated from the GitHub API in M2
        "open_prs": [],
        "labels": [],
        "milestones": [],
        "releases": [{"tag": t} for t in tags[-10:]],
        "readme_excerpt": readme,
        "_source": "git-freeze",
    }


def write_frozen(repo: str, commit: str, dest: str, lookback: int = 50, scrub: bool = True) -> dict:
    export_tree(repo, commit, dest)
    ctx = build_context(repo, commit, lookback)
    if scrub:
        ctx = scrub_context(ctx)
    with open(os.path.join(dest, CONTEXT_FILE), "w", encoding="utf-8") as f:
        json.dump(ctx, f, indent=1)
    return ctx
