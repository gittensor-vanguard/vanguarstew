"""Generate replay tasks from a repo's git history (our fork of ninja's `Generate`).

Ninja picks one commit and asks the agent to reproduce it. We instead pick a freeze
point T with enough history before it and at least `horizon` commits after it, and treat
those next-N commits as the **revealed maintainer actions** — the reference trajectory.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from benchmark.freeze import _git, parse_path_list


def linear_history(repo: str) -> list:
    """First-parent commit shas, oldest -> newest."""
    out = _git(repo, "rev-list", "--first-parent", "--reverse", "HEAD")
    return [line for line in out.splitlines() if line]


def _commit_detail(repo: str, sha: str) -> dict:
    """One revealed commit's `{sha, subject, files}` reference record."""
    subject = _git(repo, "log", "-1", "--pretty=format:%s", sha).strip()
    # `-m --first-parent` makes `git show` report the files a merge commit brought in
    # relative to its first parent — a plain `git show` of a clean merge yields a
    # combined diff with no files, silently emptying the ground truth objective scoring
    # keys off (#113). `-z` NUL-delimits the path list (parsed via `parse_path_list`) so
    # paths containing spaces, newlines, or other shell-sensitive characters survive
    # intact instead of being split apart (#116, #120, #137).
    raw = _git(repo, "show", "-m", "--first-parent", "--name-only", "-z",
               "--pretty=format:", sha, check=False)
    return {"sha": sha[:10], "subject": subject, "files": parse_path_list(raw)}


def revealed_window(repo: str, commits: list, idx: int, n: int) -> list:
    """The next `n` maintainer actions after the freeze commit (the reference)."""
    return [_commit_detail(repo, sha) for sha in commits[idx + 1: idx + 1 + n]]


def revealed_window_days(repo: str, commits: list, idx: int, days: int, dates: dict) -> list:
    """Every maintainer action landing within `days` days AFTER the freeze commit.

    The commit-count horizon is uniform in a dimension that carries no meaning and wildly
    non-uniform in the one that does: `horizon=5` is ~24 minutes of work on a repo doing ~290
    commits/day, and ~46 days on one doing ~40 commits/year — the same parameter spanning a
    ~2700x range in what "the next 5 maintainer actions" means. Over so short a span the
    ground truth is dominated by which maintainer happened to be working that hour, not by
    where the project was going. A time window makes the task mean the same thing on every
    repo and lets that idiosyncrasy average out.
    """
    freeze_dt = _as_dt(dates.get(commits[idx]))
    if freeze_dt is None:
        return []
    cutoff = freeze_dt + timedelta(days=days)
    out = []
    for sha in commits[idx + 1:]:
        landed = _as_dt(dates.get(sha))
        if landed is None or landed > cutoff:
            break  # first-parent order is chronological — past the cutoff, so is everything after
        out.append(_commit_detail(repo, sha))
    return out


def _window_commit_count(commits: list, idx: int, dts: dict, days: int) -> int:
    """How many maintainer actions land within `days` of the freeze at `idx`."""
    freeze_dt = dts.get(commits[idx])
    if freeze_dt is None:
        return 0
    cutoff = freeze_dt + timedelta(days=days)
    count = 0
    for sha in commits[idx + 1:]:
        landed = dts.get(sha)
        if landed is None or landed > cutoff:
            break  # first-parent order is chronological
        count += 1
    return count


def _space_picks_days(pool: list, commits: list, dts: dict, days: int, num_tasks: int,
                      rng: random.Random | None = None) -> list:
    """Freeze points spread across `pool`, never closer than `days` apart IN TIME.

    Commit-index spacing says nothing about day spacing: on a busy repo, evenly-strided indices
    can all land inside a single window, so one task's judged future contains the next task's
    frozen present (see `task_independence`). Stride in the dimension the window actually spans.
    Yields fewer than `num_tasks` when the pool can't hold that many disjoint windows — fewer
    honest tasks beats overlapping ones.
    """
    if not pool:
        return []
    first, last = dts[commits[pool[0]]], dts[commits[pool[-1]]]
    span = (last - first).total_seconds() / 86400.0
    # Never closer than the window span (independence), but otherwise spread across the whole
    # pool rather than clustering at its start.
    stride = max(float(days) + 1.0, span / max(1, num_tasks))
    # Anchor the picks to a FIXED grid rather than re-striding from each accepted pick: when a
    # candidate lands past its target (a quiet stretch with no commits near the grid point), a
    # relative stride carries that overshoot into every later cutoff and walks off the end of the
    # pool, silently returning fewer tasks. `rotation_seed` shifts the grid's phase, so repeated
    # runs land on different freeze points without giving up either the spread or the spacing.
    offset = rng.random() * stride if rng is not None else 0.0
    picks, last_dt, start = [], None, 0
    for k in range(num_tasks):
        target = first + timedelta(days=offset + k * stride)
        for pos in range(start, len(pool)):
            landed = dts[commits[pool[pos]]]
            if landed < target:
                continue
            if last_dt is not None and (landed - last_dt).total_seconds() / 86400.0 <= days:
                continue  # inside the previous task's revealed window
            picks.append(pool[pos])
            last_dt, start = landed, pos + 1
            break
    return picks


def _commit_dates(repo: str) -> dict[str, str]:
    """First-parent commit dates keyed by full SHA, oldest -> newest."""
    out = _git(repo, "log", "--first-parent", "--reverse", "--pretty=format:%H%x09%cI", "HEAD")
    dates = {}
    for line in out.splitlines():
        sha, _, commit_date = line.partition("\t")
        if sha and commit_date:
            dates[sha] = commit_date
    return dates


def _as_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def _as_dt(value: str | None) -> datetime | None:
    """Full ISO timestamp (not just the date) — a day-granularity window needs the time."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def generate_tasks(repo: str, num_tasks: int = 3, horizon: int = 5, min_history: int = 10,
                   recent_bias: bool = False, rotation_seed: int | None = None,
                   after: str | None = None, before: str | None = None,
                   horizon_days: int | None = None) -> list:
    """Select freeze points from history.

    - ``recent_bias``: draw only from the most recent usable window. Recent freeze points are
      preferred by the leakage strategy (more likely past a model's training cutoff).
    - ``rotation_seed``: deterministically rotate which freeze points are chosen, so tasks
      vary run-to-run and answers aren't reused. Same seed -> same picks.
    - ``after`` / ``before``: optional inclusive date bounds (`YYYY-MM-DD`) on the freeze
      commit, used by curated repo-set windows to keep tasks inside vetted leakage-safe spans.
    """
    commits = linear_history(repo)
    dates = _commit_dates(repo) if (after or before or horizon_days) else {}
    dts = {sha: _as_dt(value) for sha, value in dates.items()} if horizon_days else {}
    if horizon_days:
        # forward-history check in DAYS: the freeze needs a full `horizon_days` of real history
        # after it, or the window is silently truncated and the task is scored on a short future.
        last_dt = dts.get(commits[-1]) if commits else None
        usable = [
            i for i in range(len(commits))
            if i >= min_history
            and last_dt is not None
            and ((fd := dts.get(commits[i])) is not None)
            and fd + timedelta(days=horizon_days) <= last_dt
            # Calendar time after the freeze does NOT imply any maintainer action landed in it: a
            # quiet stretch on a slow repo leaves the window empty, and an empty revealed window is
            # an unscoreable task (`task_integrity` and `task_uniformity` both reject it). Require
            # the window to contain real work.
            and _window_commit_count(commits, i, dts, horizon_days) > 0
        ]
    else:
        usable = [i for i in range(len(commits))
                  if i >= min_history and i + horizon < len(commits)]
    if after or before:
        lower = _as_date(after)
        upper = _as_date(before)
        usable = [
            i for i in usable
            if ((d := _as_date(dates.get(commits[i]))) is not None)
            and (lower is None or d >= lower)
            and (upper is None or d <= upper)
        ]
    if not usable:
        return []

    pool = usable
    if recent_bias:
        window = max(num_tasks * 3, num_tasks)
        pool = usable[-window:]

    if horizon_days:
        picks = _space_picks_days(
            pool, commits, dts, horizon_days, num_tasks,
            random.Random(rotation_seed) if rotation_seed is not None else None)
    elif rotation_seed is not None:
        rng = random.Random(rotation_seed)
        # `random.sample` can draw adjacent indices, so a commit-horizon set is spaced by
        # `task_independence` rejecting it, not by construction.
        picks = sorted(rng.sample(pool, min(num_tasks, len(pool))))
    else:
        step = max(1, len(pool) // max(1, num_tasks))
        picks = pool[::step][:num_tasks]

    tasks = []
    for i in picks:
        task = {
            "freeze_commit": commits[i],
            "freeze_index": i,
            "revealed": (revealed_window_days(repo, commits, i, horizon_days, dates)
                         if horizon_days else revealed_window(repo, commits, i, horizon)),
        }
        if horizon_days:
            # A time window's revealed length VARIES by design (a busy month reveals more commits
            # than a quiet one), so the equal-weight and non-overlap invariants can no longer be
            # read off commit counts/indices. Record what they now need: the span every task is
            # judged over, and when the freeze actually happened. See task_uniformity (equal weight
            # = equal SPAN here) and task_independence (windows overlap in DAYS, not commits).
            task["horizon_days"] = horizon_days
            task["freeze_date"] = dates.get(commits[i])
        tasks.append(task)
    return tasks
