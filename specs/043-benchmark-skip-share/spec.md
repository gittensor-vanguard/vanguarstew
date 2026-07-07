# Spec 043 — skip share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1108
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (scored-repo coverage),
  [`benchmark/skip_budget.py`](../../benchmark/skip_budget.py) (skip gate)

This spec makes the **existing, implicit** skip-share contract explicit. It describes the
as-built behavior of `benchmark/skip_share.py`; it introduces **no behavior change**.

## Why

`scored_fraction` reports how many repos were scored; `skip_share` reports the complementary
skipped fraction `(repos - scored_repos) / repos` for CI dashboards without applying a pass/fail
gate.

## User stories

1. **As a benchmark operator**, I can read skip share before trusting a multi-repo headline mean.
2. **As a CI maintainer**, I can log a stable `skip_share_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_skip_share(artifact)` SHALL treat it
  as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Skip share (`_skip_share`)

- WHEN both `repos` and `scored` pass `_is_int` AND `repos > 0` AND `0 <= scored <= repos` THEN
  `_skip_share(repos, scored)` SHALL return `round((repos - scored) / repos, 3)`.
- WHEN `repos <= 0`, `scored < 0`, `scored > repos`, or either argument fails `_is_int` THEN
  `_skip_share` SHALL return `None`.

### Slice summary (`_slice_summary`)

- SHALL read `repos` and `scored_repos` from the slice dict.
- WHEN `_skip_share` returns a number THEN the slice SHALL include `skipped = repos - scored_repos`.
- WHEN `_skip_share` returns `None` THEN `skipped` and `skip_share` SHALL be `None`, echoing raw
  int counts when present.

### Combined summary (`_combined`)

- WHEN every input slice has `_is_int` values for both `repos` and `scored_repos` THEN `_combined`
  SHALL sum counts and compute `skip_share` via `_skip_share` on the totals.
- WHEN any slice lacks coherent counts THEN `_combined` SHALL return all fields `None`.

### Artifact-kind branches (`summarize_skip_share`)

Every summary SHALL include: `kind`, `repos`, `scored_repos`, `skipped`, `skip_share`, `partitions`.

1. **`single` or `multi`** — top-level slice; `partitions` SHALL be `None`.
2. **`generalization`** — per-partition slices plus overall from `_combined(tuned, held_out)`.
3. **`invalid`** — all count/share fields `None`, `partitions` `None`.

### Skip share headline

- `share_txt` SHALL be `f"{share:.1%}"` when `skip_share` passes `_is_number`, otherwise `n/a`.
- WHEN both `skipped` and `repos` pass `_is_int` THEN the headline SHALL be:
  `skip share: {share_txt} ({skipped} of {repos} repos skipped)`.
- OTHERWISE the headline SHALL be: `skip share: {share_txt}`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_skip_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_043_skip_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_skip_share.py`.
