"""Contract tests for specs/077-benchmark-taskgen — assert taskgen.py satisfies the spec's
EARS criteria: reference-record shape, commit-count vs time-window revealed semantics (exact-cutoff
inclusion, chronology-break early exit, missing-date guards), window occupancy, fixed-grid
time-spaced picks (strict day spacing, fewer-than-requested honesty), date parsing asymmetry,
and every `generate_tasks` branch (usable-index rules, inclusive date bounds, recent bias,
rotation-seed behaviors, task shape per mode). Literal expected values; offline, deterministic.

Complements tests/test_taskgen.py, which owns the merge-attribution (#113) and NUL path-parsing
(#116/#120/#137) angles plus the non-uniform-density spacing regressions.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.taskgen import (  # noqa: E402
    _as_date,
    _as_dt,
    _commit_dates,
    _commit_detail,
    _space_picks_days,
    _window_commit_count,
    generate_tasks,
    linear_history,
    revealed_window,
    revealed_window_days,
)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

COMMIT_KEYS = {"freeze_commit", "freeze_index", "revealed"}
TIME_KEYS = COMMIT_KEYS | {"horizon_days", "freeze_date"}


def _run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _dated_repo(dirpath, dates):
    """A linear history whose commits land at noon UTC on the given ISO dates.

    Same conventions as tests/test_taskgen.py: ``gc.auto 0`` / ``commit.gpgsign false`` keep
    rapid commits from tripping a background repack or a signing prompt.
    """
    os.makedirs(dirpath, exist_ok=True)
    _run(dirpath, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@t.t"), ("user.name", "t"),
                       ("gc.auto", "0"), ("commit.gpgsign", "false")):
        _run(dirpath, "config", key, value)
    for i, when in enumerate(dates):
        with open(os.path.join(dirpath, f"f{i}.txt"), "w", encoding="utf-8") as f:
            f.write(str(i))
        _run(dirpath, "add", "-A")
        stamp = f"{when}T12:00:00+00:00"
        subprocess.run(["git", "-C", dirpath, "commit", "-q", "-m", f"c{i}"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       env={**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    return dirpath


def _noon(day):
    """Noon UTC, `day` days after 2019-01-01 — synthetic dts entries for the pure helpers."""
    return datetime(2019, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=day)


@pytest.fixture(scope="module")
def daily_repo(tmp_path_factory):
    """12 commits c0..c11, one per day 2019-01-01 .. 2019-01-12."""
    return _dated_repo(str(tmp_path_factory.mktemp("daily")),
                       [f"2019-01-{d:02d}" for d in range(1, 13)])


@pytest.fixture(scope="module")
def sparse_repo(tmp_path_factory):
    """c0..c3 daily 2019-01-01 .. 2019-01-04, then c4 on 2019-02-15 (a quiet stretch)."""
    return _dated_repo(str(tmp_path_factory.mktemp("sparse")),
                       ["2019-01-01", "2019-01-02", "2019-01-03", "2019-01-04", "2019-02-15"])


# --- Reference records (`_commit_detail`) -------------------------------------------------

@needs_git
def test_commit_detail_shape_and_sha_prefix(daily_repo):
    commits = linear_history(daily_repo)
    detail = _commit_detail(daily_repo, commits[3])
    assert set(detail) == {"sha", "subject", "files"}
    assert detail["sha"] == commits[3][:10] and len(detail["sha"]) == 10
    assert detail["subject"] == "c3"
    assert detail["files"] == ["f3.txt"]
    # the task-level freeze pointer stays full-length; only revealed records are abbreviated
    assert all(len(sha) == 40 for sha in commits)


# --- Commit-count window (`revealed_window`) ----------------------------------------------

@needs_git
def test_revealed_window_starts_after_freeze_and_truncates(daily_repo):
    commits = linear_history(daily_repo)
    # starts at idx+1: the freeze commit itself is never part of its own reference
    assert [e["subject"] for e in revealed_window(daily_repo, commits, 0, 2)] == ["c1", "c2"]
    # silently truncates at end of history rather than padding or raising
    assert [e["subject"] for e in revealed_window(daily_repo, commits, 10, 5)] == ["c11"]
    assert revealed_window(daily_repo, commits, 11, 3) == []


# --- Time window (`revealed_window_days`) -------------------------------------------------

@needs_git
def test_revealed_window_days_includes_commit_landing_exactly_at_cutoff():
    # c2 lands exactly `days` after the freeze (noon -> noon): landed == cutoff is INSIDE the
    # window (the scan breaks only on landed > cutoff); c3 is past it.
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"),
                           ["2019-01-01", "2019-01-10", "2019-01-31", "2019-03-15"])
        commits = linear_history(repo)
        window = revealed_window_days(repo, commits, 0, 30, _commit_dates(repo))
    assert [e["subject"] for e in window] == ["c1", "c2"]


@needs_git
def test_revealed_window_days_stops_at_first_chronology_break():
    # The scan is a PREFIX walk that assumes first-parent order is chronological: once one
    # commit lands past the cutoff (c2), everything after it is dropped — including the
    # backdated c3 that actually lands inside the window.
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"),
                           ["2019-01-01", "2019-01-02", "2019-02-10", "2019-01-03"])
        commits = linear_history(repo)
        dates = _commit_dates(repo)
        window = revealed_window_days(repo, commits, 0, 30, dates)
        assert [e["subject"] for e in window] == ["c1"]
        # a missing freeze date empties the whole window
        assert revealed_window_days(repo, commits, 0, 30, {}) == []
        # a missing date mid-scan terminates the window at that commit
        partial = dict(dates)
        del partial[commits[1]]
        assert revealed_window_days(repo, commits, 0, 30, partial) == []


# --- Window occupancy (`_window_commit_count`) --------------------------------------------

def test_window_commit_count_prefix_scan_and_guards():
    shas = ["s0", "s1", "s2", "s3"]
    dts = {"s0": _noon(0), "s1": _noon(1), "s2": _noon(40), "s3": _noon(2)}
    # s2 breaks the scan, so the backdated in-window s3 is not counted
    assert _window_commit_count(shas, 0, dts, 30) == 1
    # missing freeze date -> 0, not an error
    assert _window_commit_count(shas, 0, {}, 30) == 0
    # landing exactly at the cutoff counts as inside the window
    assert _window_commit_count(["a", "b"], 0, {"a": _noon(0), "b": _noon(30)}, 30) == 1


# --- Time-spaced picks (`_space_picks_days`) ----------------------------------------------

def test_space_picks_days_strict_spacing_fixed_grid_and_honesty():
    # commits at day 0 / 20 / 30 / 31; days=10, num_tasks=4 -> grid targets 0, 11, 22, 33
    # (stride = max(days + 1, span/num) = 11). Day 30 sits exactly 10 days after the day-20
    # pick: a gap of exactly `days` is REJECTED (spacing is strictly greater-than), so the
    # scan moves on to day 31. Only 3 of the 4 requested picks fit — fewer honest tasks.
    shas = ["s0", "s1", "s2", "s3"]
    dts = {"s0": _noon(0), "s1": _noon(20), "s2": _noon(30), "s3": _noon(31)}
    assert _space_picks_days([0, 1, 2, 3], shas, dts, 10, 4) == [0, 1, 3]
    assert _space_picks_days([], shas, dts, 10, 3) == []
    # The grid is FIXED, not re-anchored at each accepted pick: commits at day 0 / 25 / 41 / 60,
    # days=10, num_tasks=3 -> stride max(11, 60/3) = 20, targets 0 / 20 / 40. The day-25 pick
    # overshoots its day-20 target by 5, but the next target stays 40 (not 25 + 20 = 45), so
    # day 41 is accepted. A re-anchoring stride would skip to day 60 and return [0, 1, 3].
    dts2 = {"s0": _noon(0), "s1": _noon(25), "s2": _noon(41), "s3": _noon(60)}
    assert _space_picks_days([0, 1, 2, 3], shas, dts2, 10, 3) == [0, 1, 2]


# --- Date parsing (`_as_date` / `_as_dt`) -------------------------------------------------

def test_as_dt_normalizes_and_rejects():
    assert _as_dt("2019-01-02T03:04:05Z") == datetime(2019, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert _as_dt(" 2019-01-02T03:04:05+00:00 ") == datetime(2019, 1, 2, 3, 4, 5,
                                                             tzinfo=timezone.utc)
    for bad in ("not-a-date", "", "   ", None, 42):
        assert _as_dt(bad) is None, bad


def test_as_date_truncates_and_raises_on_malformed():
    assert _as_date("2019-01-02T03:04:05+00:00") == date(2019, 1, 2)
    assert _as_date(None) is None and _as_date("") is None
    # asymmetric with _as_dt: a malformed NON-empty value propagates ValueError, not None
    with pytest.raises(ValueError):
        _as_date("not-a-date")


# --- `_commit_dates` ----------------------------------------------------------------------

@needs_git
def test_commit_dates_full_sha_keys_oldest_to_newest(daily_repo):
    dates = _commit_dates(daily_repo)
    assert len(dates) == 12
    assert all(len(sha) == 40 for sha in dates)
    assert [v[:10] for v in dates.values()] == [f"2019-01-{d:02d}" for d in range(1, 13)]
    assert list(dates) == linear_history(daily_repo)  # same first-parent order


# --- `generate_tasks`: commit-horizon mode ------------------------------------------------

@needs_git
def test_commit_horizon_usable_rule_stride_and_task_shape(daily_repo):
    # 12 commits, min_history=2, horizon=5: usable = [2..6] (>= 2 before, i+5 < 12).
    # Unseeded stride: step = max(1, 5 // 3) = 1 -> the first three usable indices.
    commits = linear_history(daily_repo)
    tasks = generate_tasks(daily_repo, num_tasks=3, horizon=5, min_history=2)
    assert [t["freeze_index"] for t in tasks] == [2, 3, 4]
    assert all(len(t["revealed"]) == 5 for t in tasks)
    assert all(t["freeze_commit"] == commits[t["freeze_index"]] for t in tasks)
    assert all(len(t["freeze_commit"]) == 40 for t in tasks)
    assert all(set(t) == COMMIT_KEYS for t in tasks)  # no horizon_days / freeze_date here
    assert tasks[0]["revealed"][0]["sha"] == commits[3][:10]


@needs_git
def test_commit_horizon_empty_usable_returns_empty_list(daily_repo):
    # min_history consumes all indices with a full horizon after them
    assert generate_tasks(daily_repo, num_tasks=3, horizon=5, min_history=10) == []
    # horizon longer than the whole history
    assert generate_tasks(daily_repo, num_tasks=3, horizon=20, min_history=0) == []


@needs_git
def test_commit_horizon_rotation_seed_sample(daily_repo):
    # num_tasks >= pool: the sample is the whole pool, sorted ascending
    tasks = generate_tasks(daily_repo, num_tasks=10, horizon=5, min_history=2, rotation_seed=7)
    assert [t["freeze_index"] for t in tasks] == [2, 3, 4, 5, 6]
    # same seed -> same picks; picks always ascending and drawn from the usable pool
    a = generate_tasks(daily_repo, num_tasks=2, horizon=5, min_history=2, rotation_seed=7)
    b = generate_tasks(daily_repo, num_tasks=2, horizon=5, min_history=2, rotation_seed=7)
    picks = [t["freeze_index"] for t in a]
    assert picks == [t["freeze_index"] for t in b]
    assert len(picks) == 2 and picks == sorted(picks)
    assert set(picks) <= {2, 3, 4, 5, 6}


@needs_git
def test_recent_bias_draws_from_last_three_n_usable(daily_repo):
    # usable = [2..6]; recent_bias trims the pool to the last 3*num_tasks = 3 -> [4, 5, 6],
    # stride step = 3 -> pick 4. Without bias the stride starts at the pool head -> pick 2.
    biased = generate_tasks(daily_repo, num_tasks=1, horizon=5, min_history=2, recent_bias=True)
    plain = generate_tasks(daily_repo, num_tasks=1, horizon=5, min_history=2)
    assert [t["freeze_index"] for t in biased] == [4]
    assert [t["freeze_index"] for t in plain] == [2]


@needs_git
def test_date_bounds_are_inclusive_on_both_ends(daily_repo):
    # daily commits Jan 1..12; after/before keep freeze DATES in [Jan 3, Jan 5] inclusive
    tasks = generate_tasks(daily_repo, num_tasks=12, horizon=1, min_history=0,
                           after="2019-01-03", before="2019-01-05")
    assert [t["freeze_index"] for t in tasks] == [2, 3, 4]
    lower_only = generate_tasks(daily_repo, num_tasks=12, horizon=1, min_history=0,
                                after="2019-01-11")
    assert [t["freeze_index"] for t in lower_only] == [10]
    assert generate_tasks(daily_repo, num_tasks=12, horizon=1, min_history=0,
                          after="2019-02-01") == []


# --- `generate_tasks`: time-horizon mode --------------------------------------------------

@needs_git
def test_time_horizon_usable_rule_and_task_shape(sparse_repo):
    # horizon_days=7, min_history=2: c2 (Jan 3) is the only usable freeze — c3's 7-day window
    # is empty (next commit lands Feb 15) and c4 has no 7 days of forward history at all.
    tasks = generate_tasks(sparse_repo, num_tasks=2, min_history=2, horizon_days=7)
    assert [t["freeze_index"] for t in tasks] == [2]
    task = tasks[0]
    assert set(task) == TIME_KEYS  # horizon_days + freeze_date appear ONLY in this mode
    assert task["horizon_days"] == 7
    assert task["freeze_date"][:10] == "2019-01-03"  # the freeze commit's raw %cI date
    assert [e["subject"] for e in task["revealed"]] == ["c3"]


@needs_git
def test_time_horizon_without_full_forward_history_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), ["2019-01-01", "2019-01-02", "2019-01-03"])
        assert generate_tasks(repo, num_tasks=2, min_history=0, horizon_days=30) == []


@needs_git
def test_time_horizon_excludes_freezes_whose_window_holds_no_work():
    # Jan 3 has a full 7 days of forward calendar history (history runs to Feb 16) but not one
    # commit lands inside Jan 3 + 7d — calendar time alone does not make a freeze usable, so no
    # task is generated at all (the later freezes lack full forward history instead).
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), [
            "2019-01-01", "2019-01-02", "2019-01-03", "2019-02-15", "2019-02-16"])
        assert generate_tasks(repo, num_tasks=2, min_history=2, horizon_days=7) == []


@needs_git
def test_time_horizon_forward_history_boundary_is_inclusive():
    # Jan 3 + 7d lands exactly ON the last commit (Jan 10): "at least horizon_days of forward
    # history" is inclusive, and the boundary commit is real work inside the window.
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"), [
            "2019-01-01", "2019-01-02", "2019-01-03", "2019-01-10"])
        tasks = generate_tasks(repo, num_tasks=2, min_history=2, horizon_days=7)
        assert [t["freeze_index"] for t in tasks] == [2]


@needs_git
def test_horizon_days_zero_falls_back_to_commit_mode(daily_repo):
    # the mode switch tests truthiness, not None-ness: horizon_days=0 is commit-horizon mode
    tasks = generate_tasks(daily_repo, num_tasks=1, horizon=5, min_history=2, horizon_days=0)
    assert tasks and set(tasks[0]) == COMMIT_KEYS


@needs_git
def test_date_bounds_apply_in_time_mode_too():
    with tempfile.TemporaryDirectory() as tmp:
        repo = _dated_repo(os.path.join(tmp, "r"),
                           ["2019-01-01", "2019-01-02", "2019-01-03", "2019-01-04",
                            "2019-01-05", "2019-02-15"])
        unbounded = generate_tasks(repo, num_tasks=3, min_history=0, horizon_days=7)
        bounded = generate_tasks(repo, num_tasks=3, min_history=0, horizon_days=7,
                                 after="2019-01-02")
    assert [t["freeze_index"] for t in unbounded] == [0]
    assert [t["freeze_index"] for t in bounded] == [1]


@needs_git
def test_time_horizon_seeded_rotation_may_drop_sparse_pool_picks(sparse_repo):
    # The rotation seed only shifts the grid PHASE (offset = rng.random() * stride, the one
    # rng draw — guaranteed stable across CPython versions). On a one-candidate pool the
    # shifted first target can land past that candidate, so the seeded run honestly yields
    # ZERO tasks where the unseeded (offset 0) run yields one.
    seeded = generate_tasks(sparse_repo, num_tasks=2, min_history=2, horizon_days=7,
                            rotation_seed=3)
    unseeded = generate_tasks(sparse_repo, num_tasks=2, min_history=2, horizon_days=7)
    assert seeded == []
    assert [t["freeze_index"] for t in unseeded] == [2]
