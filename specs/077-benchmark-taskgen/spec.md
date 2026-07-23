# Spec 077 — replay task generation

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1952
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/taskgen.py`](../../benchmark/taskgen.py) (the generator this spec binds),
  [`benchmark/freeze.py`](../../benchmark/freeze.py) (the `_git` runner and `parse_path_list`,
  Spec 021), [`specs/005-repo-set`](../005-repo-set/spec.md) (which repos tasks are drawn from),
  [`specs/021-benchmark-freeze-path-parse`](../021-benchmark-freeze-path-parse/spec.md) (the NUL
  path parser `_commit_detail` consumes),
  [`specs/055-benchmark-task-independence`](../055-benchmark-task-independence/spec.md) and
  [`specs/057-benchmark-task-integrity`](../057-benchmark-task-integrity/spec.md) (gates over the
  generated task set)

This spec makes the **existing, implicit** task-generation contract explicit. It describes the
as-built behavior of `benchmark/taskgen.py`; it introduces **no behavior change**. The sibling
specs cover adjacent concerns, not this one: 005 curates the *input* corpus, 021 pins the path
*parser*, and 055/057 (with 056) are *checks over the generator's output*. Nothing yet documents
the generator itself — the freeze-point selection rules, the two horizon modes, and the task-dict
shape those gates and `run_replay` consume.

## Why

`generate_tasks` decides what the benchmark *is*: which freeze points a repo yields, what counts
as the revealed reference trajectory, and which keys a task record carries. The integrity gates
(task_integrity / task_uniformity / task_independence) can only reject a bad task set after the
fact; the selection rules that make sets pass those gates by construction — full forward history,
non-empty windows, day-spaced picks, inclusive date bounds — live only in code and comments.
Writing them down lets reviewers check taskgen changes against intent, and pins the subtle
mode-dependent task shape (`horizon_days`/`freeze_date` keys exist **only** on time-horizon
tasks) that downstream consumers key off.

## User stories

1. **As a benchmark operator**, I can predict which freeze points a repo yields for a given
   `min_history`/`horizon`/`horizon_days`/bounds configuration, and how `rotation_seed` varies
   them run-to-run.
2. **As a reviewer**, the usable-index rules, both window semantics (including the
   chronology-break early exit), and the per-mode task shape are written down — so a taskgen
   change is checked against the spec instead of re-derived from code.
3. **As a gate maintainer**, I know what the generator guarantees by construction (non-empty
   time windows, day-spaced picks) versus what my gate must still verify.

## Constants

- `generate_tasks` defaults SHALL be `num_tasks=3`, `horizon=5`, `min_history=10`.
- The revealed-record SHA prefix SHALL be 10 characters (`sha[:10]`); `freeze_commit` stays
  full-length.
- The recent-bias pool SHALL be the last `max(num_tasks * 3, num_tasks)` usable indices.
- The time-spacing stride SHALL be `max(days + 1.0, span / max(1, num_tasks))` days, with day
  arithmetic at `86400.0` seconds per day.

## Acceptance criteria (EARS)

### History enumeration (`linear_history`, `_commit_dates`)

- `linear_history(repo)` SHALL return first-parent commit SHAs (full 40-char), oldest → newest;
  commits reachable only through a merged side branch SHALL NOT appear.
- `_commit_dates(repo)` SHALL return `{full_sha: committer_date}` for the same first-parent walk
  in the same oldest → newest order, with values in git `%cI` strict-ISO form (which MAY be
  `Z`-suffixed depending on the git build); rows missing a SHA or date are dropped.

### Reference records (`_commit_detail`)

- `_commit_detail(repo, sha)` SHALL return exactly `{"sha", "subject", "files"}` with `sha`
  abbreviated to the first 10 characters of the full SHA.
- `files` SHALL come from `git show -m --first-parent --name-only -z` parsed by
  `parse_path_list`, so a merge commit reports the files it brought in relative to its first
  parent (#113) and paths with spaces/newlines survive intact (#116, #120, #137).

### Commit-count window (`revealed_window`)

- `revealed_window(repo, commits, idx, n)` SHALL return reference records for
  `commits[idx + 1 : idx + 1 + n]` — the freeze commit itself is never part of its own
  reference.
- WHEN fewer than `n` commits remain after `idx` THEN the window SHALL be silently truncated
  (empty at the history end), never padded and never an error.

### Time window (`revealed_window_days`)

- WHEN the freeze commit's date is missing or unparsable THEN the window SHALL be `[]`.
- The cutoff SHALL be `freeze_datetime + days`; a commit landing **exactly at** the cutoff is
  inside the window (the scan breaks only on `landed > cutoff`).
- The scan SHALL be a **prefix walk** that assumes first-parent order is chronological: it stops
  at the first commit whose date is missing/unparsable or past the cutoff. On a non-monotonic
  history, an in-window commit that appears *after* a past-cutoff commit is therefore excluded —
  the function returns the chronological prefix, not literally "every" in-window action.

### Window occupancy (`_window_commit_count`)

- `_window_commit_count(commits, idx, dts, days)` SHALL count commits after `idx` landing at or
  before the cutoff, with the same prefix-walk early exit as `revealed_window_days`.
- WHEN the freeze date is missing THEN the count SHALL be `0` (not an error).

### Time-spaced picks (`_space_picks_days`)

- WHEN `pool` is empty THEN the result SHALL be `[]`.
- Candidate targets SHALL lie on a **fixed grid** anchored at the first pool commit's date:
  `target_k = first + offset + k * stride` — an overshoot at one pick does not shift later
  targets.
- WHEN `rng` is provided THEN `offset` SHALL be `rng.random() * stride` (one draw — the
  version-stable part of `random`); OTHERWISE `offset` SHALL be `0.0`.
- A candidate SHALL be rejected when its gap to the previous accepted pick is `<= days` — a gap
  of **exactly** `days` is rejected; spacing is strictly greater-than.
- The function SHALL yield fewer than `num_tasks` picks when the pool cannot hold that many
  disjoint windows — including **zero** picks when the phase offset pushes the first grid target
  past a sparse pool's only candidate. Fewer honest tasks beats overlapping ones.

### Date parsing (`_as_date`, `_as_dt`)

- `_as_dt` SHALL accept a strict-ISO timestamp, normalizing a trailing `Z` to `+00:00` and
  stripping surrounding whitespace; a non-`str`, blank, or unparsable value SHALL yield `None`.
- `_as_date` SHALL truncate to the first 10 characters and parse as a date; a falsy value SHALL
  yield `None`. **Asymmetry (as-built):** a malformed *non-empty string* propagates `ValueError`
  — only `_as_dt` swallows parse failures. `_as_date` is only ever fed git `%cI` output or
  operator-supplied `after`/`before` bounds, where failing loudly on a typo is the desired
  fail-fast.

### Freeze-point selection (`generate_tasks`)

#### Usable indices

- In **commit-horizon** mode (`horizon_days` falsy — note `0` selects this mode; the switch
  tests truthiness, not `None`-ness), index `i` SHALL be usable iff `i >= min_history` (at least
  `min_history` commits before it) and `i + horizon < len(commits)` (a full `horizon` commits
  after it).
- In **time-horizon** mode, index `i` SHALL be usable iff `i >= min_history`, the freeze date
  parses, the history's last commit lands at least `horizon_days` after the freeze (a full
  window of real forward history — never a silently truncated one), **and**
  `_window_commit_count(...) > 0` (calendar time alone is not enough: an empty revealed window
  is an unscoreable task).
- `after`/`before` SHALL further filter usable indices by freeze **date**, inclusive on both
  ends, in **either** mode; an index whose date is missing is excluded when bounds are given.
- WHEN no usable index survives THEN the result SHALL be `[]`.

#### Pool and picks

- WHEN `recent_bias` is set THEN the pool SHALL be the last `max(num_tasks * 3, num_tasks)`
  usable indices; otherwise the whole usable list.
- In time-horizon mode picks SHALL come from `_space_picks_days`, seeded with
  `random.Random(rotation_seed)` when `rotation_seed is not None`.
- In commit-horizon mode WHEN `rotation_seed is not None` THEN picks SHALL be
  `sorted(rng.sample(pool, min(num_tasks, len(pool))))` — same seed, same picks; adjacent
  indices are possible (spacing is `task_independence`'s job, not construction's).
- OTHERWISE picks SHALL stride the pool from its head:
  `pool[::max(1, len(pool) // max(1, num_tasks))]`
  truncated to `num_tasks`.

#### Task shape

- Every task SHALL carry exactly `freeze_commit` (full SHA), `freeze_index`, and `revealed`
  (from `revealed_window_days` in time mode, else `revealed_window`).
- `horizon_days` and `freeze_date` (the freeze commit's raw `%cI` string) SHALL be present
  **only** on time-horizon tasks — commit-horizon tasks carry neither key.

## Out of scope

- The gates that verify generated sets (`task_integrity`, `task_uniformity`,
  `task_independence` — Specs 055–057) and repo curation (Spec 005).
- `parse_path_list` internals (Spec 021) and the freeze/scrub pipeline.
- Tuning any default or threshold.

## Verification

- `tests/test_spec_077_taskgen.py` exercises each EARS block above against tiny throwaway git
  repos with pinned committer dates: reference-record shape, window start/truncation,
  exact-cutoff inclusion, the chronology-break early exit and missing-date guards, strict
  greater-than day spacing on a fixed grid, fewer/zero-picks honesty, the `_as_date`/`_as_dt`
  asymmetry, both usable-index rules, inclusive bounds in both modes, recent bias, seeded and
  unseeded pick strategies, and the per-mode task key sets — all pinned as **literal** indices,
  subjects, and key sets, never re-derived from the module.
- Merge-attribution (#113), NUL path parsing (#116/#120/#137) and the non-uniform-density
  spacing regressions remain covered by `tests/test_taskgen.py`, which also spot-checks per-mode
  task-key presence; this file pins the exact per-mode key sets rather than presence alone.
