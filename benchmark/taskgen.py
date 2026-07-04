"""Generate replay tasks from a repo's git history (our fork of ninja's `Generate`).

Ninja picks one commit and asks the agent to reproduce it. We instead pick a freeze
point T with enough history before it and at least `horizon` commits after it, and treat
those next-N commits as the **revealed maintainer actions** — the reference trajectory.
"""

from __future__ import annotations

import random

from benchmark.freeze import _git, parse_path_list


def linear_history(repo: str) -> list:
    """First-parent commit shas, oldest -> newest."""
    out = _git(repo, "rev-list", "--first-parent", "--reverse", "HEAD")
    return [line for line in out.splitlines() if line]


def revealed_window(repo: str, commits: list, idx: int, n: int) -> list:
    """The next `n` maintainer actions after the freeze commit (the reference)."""
    window = []
    for sha in commits[idx + 1: idx + 1 + n]:
        subject = _git(repo, "log", "-1", "--pretty=format:%s", sha).strip()
        # `-z` emits NUL-delimited paths so filenames with spaces or shell-sensitive
        # characters aren't split apart (whitespace `.split()` corrupts them). For a
        # first-parent merge the combined diff lists no files, so this stays empty —
        # matching the prior behavior.
        out = _git(repo, "show", "--name-only", "-z", "--pretty=format:", sha, check=False)
        files = parse_path_list(out)
        window.append({"sha": sha[:10], "subject": subject, "files": files[:20]})
    return window


def generate_tasks(repo: str, num_tasks: int = 3, horizon: int = 5, min_history: int = 10,
                   recent_bias: bool = False, rotation_seed: int | None = None) -> list:
    """Select freeze points from history.

    - ``recent_bias``: draw only from the most recent usable window. Recent freeze points are
      preferred by the leakage strategy (more likely past a model's training cutoff).
    - ``rotation_seed``: deterministically rotate which freeze points are chosen, so tasks
      vary run-to-run and answers aren't reused. Same seed -> same picks.
    """
    commits = linear_history(repo)
    usable = [i for i in range(len(commits)) if i >= min_history and i + horizon < len(commits)]
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
