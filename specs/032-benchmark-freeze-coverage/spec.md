# Spec 032 — freeze coverage summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #928
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/freeze_digest.py`](../../benchmark/freeze_digest.py) (freeze fingerprints),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** freeze-coverage contract explicit. It describes the
as-built behavior of `benchmark/freeze_coverage.py`; it introduces **no behavior change**. A
multi-repo or generalization replay must not be trusted as leakage-safe when most per-repo rows
lack a pinned `freeze_commit` — that audit signal must be written down and verified.

## Why

`freeze_digest` fingerprints which freeze commits were used, but nothing summarizes how completely
a run pinned every repo it touched. `summarize_freeze_coverage()` is the reproducible read-only
summary for CI dashboards; making its contract explicit lets reviewers check freeze-coverage
changes against intent.

## User stories

1. **As a benchmark operator**, I can read how many per-repo rows carried a `freeze_commit` before
   trusting a multi-repo or generalization artifact.
2. **As a CI maintainer**, I can log a stable `freeze_coverage_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_freeze_coverage(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Freeze-commit detection (`_has_freeze_commit`)

- WHEN a per-repo row's `freeze_commit` is a non-empty `str` THEN the row SHALL count as frozen.
- WHEN `freeze_commit` is missing, an empty string, or not a `str` THEN the row SHALL NOT count
  as frozen.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]` without warning.
- WHEN `per_repo` is not a `list` THEN `_rows_from_per_repo` SHALL log a warning and return `[]`
  (not raise).
- WHEN a list entry is not a `dict` THEN that entry SHALL be skipped with a warning; remaining
  dict rows SHALL still be counted.

### Slice summary (`_slice_summary`)

- `repos_total` SHALL be the count of usable dict rows after parsing.
- `repos_frozen` SHALL be the count of rows where `_has_freeze_commit` is true.
- WHEN `repos_total > 0` THEN `freeze_coverage` SHALL be `round(repos_frozen / repos_total, 3)`.
- WHEN `repos_total == 0` THEN `freeze_coverage` SHALL be `None` (distinct from a real `0.0`
  rate on a single-repo artifact with no freeze pin).

### Artifact-kind branches (`summarize_freeze_coverage`)

Classification SHALL use `artifact_kind` from `benchmark.comparability`.

1. **`single`** — `repos_total` SHALL be `1`; `repos_frozen` SHALL be `1` when the top-level
   artifact carries a non-empty `freeze_commit`, otherwise `0`; `freeze_coverage` SHALL be
   `float(repos_frozen)` (`0.0` or `1.0`); `partitions` SHALL be `None`.
2. **`multi`** — summary fields SHALL come from `_slice_summary(artifact["per_repo"])`;
   `partitions` SHALL be `None`.
3. **`generalization`** — SHALL report per-partition stats under `partitions["tuned"]` and
   `partitions["held_out"]` (each via `_slice_summary` on that partition's `per_repo`), plus
   aggregate `repos_total`, `repos_frozen`, and `freeze_coverage` summed across both partitions;
   WHEN the aggregate `repos_total == 0` THEN aggregate `freeze_coverage` SHALL be `None`.
4. **`invalid` or other** — SHALL return `repos_total = 0`, `repos_frozen = 0`,
   `freeze_coverage = None`, and `partitions = None`.

Every summary SHALL include `kind` echoing `artifact_kind`.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline rate
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Freeze coverage headline

- `freeze_coverage_headline(summary)` SHALL return a one-line human summary.
- WHEN `repos_total` is not a whole `int` or is `<= 0` THEN the headline SHALL read
  `freeze coverage: no per-repo rows` — regardless of `kind` or other fields.
- WHEN usable totals exist and `kind == "generalization"` THEN the headline SHALL include the
  aggregate rate, `repos_frozen/repos_total`, and tuned/held-out partition rates.
- WHEN usable totals exist and `kind` is not `generalization` THEN the headline SHALL include the
  aggregate rate and `repos_frozen/repos_total` without partition brackets.
- WHEN `freeze_coverage` (or a partition rate) is non-finite or non-numeric THEN the formatted
  rate SHALL display as `n/a` rather than raising.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_freeze_coverage()` SHALL NOT mutate its input dict.

## Out of scope

- Freeze fingerprint digests (`benchmark/freeze_digest.py`).
- Repo-set freeze-window validation (`benchmark/repo_set.py`).
- Changing `run_replay` / `run_multi_replay` freeze pinning semantics.

## Verification

- `tests/test_spec_032_freeze_coverage.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_freeze_coverage.py`.
