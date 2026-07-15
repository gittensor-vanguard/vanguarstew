# Spec 061 — artifact snapshot summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1703
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind),
  [`benchmark/margin_outlook.py`](../../benchmark/margin_outlook.py) (decisive-margin telemetry)

This spec makes the **existing, implicit** artifact-snapshot contract explicit. It describes the
as-built behavior of `benchmark/artifact_snapshot.py`; it introduces **no behavior change**.

## Why

`report` renders Markdown and `headline_score` returns only one number. `snapshot` fills the gap
with a stable JSON-friendly summary for CI logging and dashboards: kind, headline, task/repo
counts, decisive margin, offline/error flags.

## User stories

1. **As a benchmark operator**, I can index a replay artifact with one compact JSON object.
2. **As a CI maintainer**, I can log a stable `snapshot_headline()` string.
3. **As a reviewer**, every malformed-field and empty-slice branch is written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `snapshot(artifact)` SHALL treat it as `{}`
  and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_int(value)` SHALL be true only for built-in `int` values that are not `bool`.

### Numeric semantics (`_is_number`)

- Only **finite**, non-boolean `int`/`float` values SHALL count as numeric.
- `bool`, `str`, `None`, `NaN`, `Infinity`, and ints that overflow float SHALL NOT.

### Task total (`_per_repo_tasks`, `_task_total`)

- WHEN top-level `tasks` is numeric THEN `_task_total` SHALL return `int(tasks)`.
- WHEN `kind` is `generalization` and top-level `tasks` is absent/non-numeric THEN the sum of
  each partition's `_per_repo_tasks` SHALL be used (`None` only when both partitions yield
  `None`).
- OTHERWISE `_task_total` SHALL return `_per_repo_tasks(per_repo)`.
- `_per_repo_tasks` SHALL return `None` when `per_repo` is `None` or not a list (warning on
  non-list); `0` when the list has no numeric `tasks` rows; else the sum of numeric row
  `tasks` (skipping non-dict rows and non-numeric `tasks`).

### Repo tally (`_repo_tally`)

- WHEN `repos` and `scored_repos` are ints, `repos > 0`, and `0 <= scored_repos <= repos` THEN
  `_repo_tally` SHALL return `{total, scored, skipped}` with `skipped = repos - scored`.
- WHEN optional `skipped` is present and not equal to `repos - scored` THEN `_repo_tally`
  SHALL return `None`.
- OTHERWISE `_repo_tally` SHALL return `None`.

### Error flag (`_has_error`)

- WHEN top-level `error` is truthy THEN `_has_error` SHALL be `True`.
- WHEN `kind` is `generalization` THEN any partition with `_partition_error` SHALL set `True`.
- WHEN `kind` is `multi` THEN `_partition_error({"per_repo": ...})` SHALL decide the flag
  (bare non-empty string `per_repo` rows count as errors; blank strings do not).
- OTHERWISE `_has_error` SHALL be `False`.

### Decisive margin (`_decisive_margin`)

- WHEN top-level `decisive_margin` is numeric THEN that value SHALL be returned.
- OTHERWISE WHEN `judge_report.wins` and `.losses` are ints (from `tuned` when
  `kind == generalization`, else the artifact) THEN `wins - losses` SHALL be returned.
- OTHERWISE `None`.

### Snapshot (`snapshot`)

Every result SHALL include: `kind`, `headline_score`, `scored`, `tasks`, `repos`,
`generalization_gap`, `repo_set`, `decisive_margin`, `offline`, `has_error`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- `headline_score` SHALL come from `headline_score(artifact)`; `scored` SHALL be
  `headline_score is not None`.
- `generalization_gap` SHALL be the numeric gap or `None`.
- `repo_set` SHALL be a `str` or `None`.
- `offline` SHALL be a `bool` or `None`.
- `repos` SHALL be `_repo_tally(tuned)` for generalization, `_repo_tally(artifact)` for
  multi, else `None`.

### Snapshot headline

- Headline SHALL be:
  `snapshot: {kind} headline={score_txt} tasks={tasks_txt} status={err}`
  where `score_txt`/`tasks_txt` are `{:.3f}` / `str(...)` when numeric else `n/a`, and
  `err` is `error` when `has_error` else `ok`.
- Missing/non-dict summary SHALL coerce via `_dict` (kind defaults to `unknown`).

### Pure evaluation

- The module SHALL perform no I/O.
- `snapshot()` SHALL NOT mutate its input dict.

## Out of scope

- Markdown report rendering (`benchmark/report.py`).
- Changing `headline_score` / `_partition_error` semantics.

## Verification

- `tests/test_spec_061_artifact_snapshot.py` exercises each EARS block above, including
  non-finite fields, malformed `per_repo`, and every headline branch.
- Broader coverage (including CLI) remains in `tests/test_artifact_snapshot.py`.
