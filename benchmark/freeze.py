"""Freeze a repo at commit T and build the leakage-safe, knowable-at-T context.

We export the working tree at T and write `.vanguarstew_context.json` alongside it, derived
only from history up to and including T (commits, tags-as-releases, README). The agent
reads that — it never sees anything after T.
"""

from __future__ import annotations

import json
import os
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


def export_tree(repo: str, commit: str, dest: str) -> None:
    os.makedirs(dest, exist_ok=True)
    proc = subprocess.Popen(
        ["git", "-C", repo, "archive", "--format=tar", commit],
        stdout=subprocess.PIPE,
    )
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
        try:
            tf.extractall(dest, filter="data")  # py>=3.12
        except TypeError:
            tf.extractall(dest)
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
