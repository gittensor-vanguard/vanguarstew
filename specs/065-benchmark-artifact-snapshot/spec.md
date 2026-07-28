# Spec 065 — replay artifact snapshot

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1703 (opened as "Spec 061"; that number was taken by objective-integrity, so this
  contract is filed as Spec 065 — the next free number)
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/artifact_snapshot.py`](../../benchmark/artifact_snapshot.py) (the module
  under test), [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (`artifact_kind`),
  [`benchmark/report.py`](../../benchmark/report.py) (the human Markdown renderer this complements)

This spec makes the **existing, implicit** snapshot contract explicit. It describes the as-built
behavior of `benchmark/artifact_snapshot.py`; it introduces **no behavior change**.

## Why

`report` renders Markdown for humans and `trend.headline_score` returns only the headline number.
`snapshot` fills the gap with a compact, stable, JSON-friendly summary for CI logging, dashboards,
and artifact indexes. Because it is a fail-soft summarizer of miner/CI-controlled input, its
"degrade to `None` rather than raise" behavior across every malformed field is the contract that
matters, and this spec pins it.

## User stories

1. **As a CI dashboard**, I get a fixed-shape dict for any artifact (single-repo, multi-repo,
   `--generalization`, or malformed) whose fields are either a valid value or `None`.
2. **As a log line**, `snapshot_headline` renders a one-line summary that never raises on a
   partial/malformed snapshot.
3. **As a reviewer**, every malformed-input, wrong-shape, and per-shape derivation branch is written
   down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Acceptance criteria (EARS)

### Numeric helpers

- `_is_number(value)` SHALL be true only for a non-boolean, finite `int`/`float`; a `NaN`/`inf`
  SHALL be false, and an oversized `int` (`math.isfinite` raising `OverflowError`) SHALL be false.
- `_is_int(value)` SHALL be true only for a non-boolean `int`.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Task counting (`_per_repo_tasks`, `_task_total`)

- WHEN `per_repo` is `None` THEN `_per_repo_tasks` SHALL return `None`.
- WHEN `per_repo` is not a list THEN it SHALL warn and return `None`.
- It SHALL sum `int(tasks)` over each dict entry whose `tasks` is `_is_number`, skipping (and
  warning on) non-dict entries and silently skipping entries with a non-numeric `tasks`; WHEN at
  least one numeric `tasks` was seen it SHALL return the sum, OTHERWISE `0`.
- `_task_total(artifact)` SHALL return `int(tasks)` when the top-level `tasks` is `_is_number`.
- OTHERWISE WHEN the artifact is `generalization` THEN it SHALL sum the `tuned.per_repo` and
  `held_out.per_repo` task totals, returning `None` only when **both** partitions yield `None`,
  else `(tuned or 0) + (held or 0)`.
- OTHERWISE it SHALL return `_per_repo_tasks(artifact.per_repo)`.

### Repo tally (`_repo_tally`)

- `_repo_tally` SHALL return `None` unless both `repos` and `scored_repos` are `_is_int`.
- It SHALL return `None` when `repos <= 0`, `scored_repos < 0`, or `scored_repos > repos`.
- WHEN a `skipped` field is present it SHALL be `None` unless `skipped` is `_is_int` and equals
  `repos - scored_repos`.
- OTHERWISE it SHALL return `{"total": repos, "scored": scored_repos, "skipped": repos - scored}`.

### Error detection (`_has_error`)

- WHEN the artifact carries a truthy top-level `error` THEN `_has_error` SHALL be true.
- WHEN the artifact is `generalization` THEN it SHALL be true when either `tuned` or `held_out`
  reports a partition error (`benchmark.acceptance._partition_error`).
- WHEN the artifact is `multi` THEN it SHALL be true when its `per_repo` reports a partition error.
- A single-repo artifact with no top-level `error` SHALL be false.

### Decisive margin (`_decisive_margin`)

- WHEN the top-level `decisive_margin` is `_is_number` THEN it SHALL be returned as-is.
- OTHERWISE the `judge_report` of the `tuned` partition (for a `generalization` artifact) or of the
  artifact itself SHALL supply `wins - losses` when both are `_is_int`, else `None`.

### Snapshot body (`snapshot`)

- `snapshot(artifact)` SHALL coerce a non-dict artifact to `{}` and return a dict carrying exactly
  the keys `kind`, `headline_score`, `scored`, `tasks`, `repos`, `generalization_gap`, `repo_set`,
  `decisive_margin`, `offline`, `has_error`.
- `kind` SHALL be `benchmark.comparability.artifact_kind(artifact)`; `headline_score` SHALL be
  `benchmark.trend.headline_score(artifact)`; `scored` SHALL be `headline_score is not None`.
- `generalization_gap` SHALL be the artifact value only when `_is_number`, else `None`; `repo_set`
  SHALL be the value only when it is a `str`, else `None`; `offline` SHALL be the value only when it
  is a `bool`, else `None`.
- `repos` SHALL default to `None`; for a `generalization` artifact it SHALL be the `_repo_tally` of
  the `tuned` partition; for a `multi` artifact it SHALL be the `_repo_tally` of the artifact.

### Headline (`snapshot_headline`)

- `snapshot_headline(summary)` SHALL coerce a non-dict summary to `{}` and render exactly
  `snapshot: {kind} headline={score} tasks={tasks} status={status}` where `kind` defaults to
  `unknown`, `score` is `{:.3f}` when `_is_number` else `n/a`, `tasks` is `str(tasks)` when
  `_is_number` else `n/a`, and `status` is `error` when `has_error` is truthy else `ok`.

### Pure evaluation

- The module SHALL perform no I/O.
- `snapshot()` SHALL NOT mutate its input.

## Out of scope

- Changing `headline_score` (Spec — `trend`) or `artifact_kind` (`comparability`) semantics.
- The human Markdown renderer (`report`).

## Verification

- `tests/test_spec_065_artifact_snapshot.py` exercises each EARS block above, pinning **literal**
  expected values rather than re-deriving them from the module.
- Broader coverage remains in `tests/test_artifact_snapshot.py`.
