"""Generate replay tasks from a repo's git history (our fork of ninja's `Generate`).

Ninja picks one commit and asks the agent to reproduce it. We instead pick a freeze
point T with enough history before it and at least `horizon` commits after it, and treat
those next-N commits as the **revealed maintainer actions** — the reference trajectory.
"""

from __future__ import annotations

import random

from benchmark.freeze import _git


def linear_history(repo: str) -> list:
    """First-parent commit shas, oldest -> newest."""
    out = _git(repo, "rev-list", "--first-parent", "--reverse", "HEAD")
    return [line for line in out.splitlines() if line]


def history_with_dates(repo: str) -> list[dict]:
    """First-parent commit history with ISO dates, oldest -> newest."""
    out = _git(repo, "log", "--first-parent", "--reverse", "--format=%H%x09%cI", "HEAD")
    history = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[0]:
            history.append({"sha": parts[0], "date": parts[1]})
    return history


def revealed_window(repo: str, commits: list, idx: int, n: int) -> list:
    """The next `n` maintainer actions after the freeze commit (the reference)."""
    window = []
    for sha in commits[idx + 1: idx + 1 + n]:
        subject = _git(repo, "log", "-1", "--pretty=format:%s", sha).strip()
        files = _git(repo, "show", "--name-only", "--pretty=format:", sha, check=False).split()
        window.append({"sha": sha[:10], "subject": subject, "files": files[:20]})
    return window


def generate_tasks(repo: str, num_tasks: int = 3, horizon: int = 5, min_history: int = 10,
                   recent_bias: bool = False, rotation_seed: int | None = None,
                   after: str | None = None, before: str | None = None) -> list:
    """Select freeze points from history.

    - ``recent_bias``: draw only from the most recent usable window. Recent freeze points are
      preferred by the leakage strategy (more likely past a model's training cutoff).
    - ``rotation_seed``: deterministically rotate which freeze points are chosen, so tasks
      vary run-to-run and answers aren't reused. Same seed -> same picks.
    - ``after`` / ``before``: optional YYYY-MM-DD bounds on the freeze commit date.
    """
    dates = None
    if after is not None or before is not None:
        history = history_with_dates(repo)
        commits = [item["sha"] for item in history]
        dates = [item["date"][:10] for item in history]
    else:
        commits = linear_history(repo)

    def _in_window(index: int) -> bool:
        if dates is None:
            return True
        day = dates[index]
        if after is not None and day < after:
            return False
        if before is not None and day > before:
            return False
        return True

    usable = [
        i for i in range(len(commits))
        if i >= min_history and i + horizon < len(commits) and _in_window(i)
    ]
    if not usable:
        return []

    pool = usable
    if recent_bias:
        window = max(num_tasks * 3, num_tasks)
        pool = usable[-window:]

    if rotation_seed is not None:
        rng = random.Random(rotation_seed)
        picks = sorted(rng.sample(pool, min(num_tasks, len(pool))))
    else:
        step = max(1, len(pool) // max(1, num_tasks))
        picks = pool[::step][:num_tasks]

    tasks = []
    for i in picks:
        tasks.append({
            "freeze_commit": commits[i],
            "freeze_index": i,
            "revealed": revealed_window(repo, commits, i, horizon),
        })
    return tasks
