# Spec 030 — judge tally integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #901
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/sample_adequacy.py`](../../benchmark/sample_adequacy.py) (top-level tally sum gate),
  [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (per-task row shape gate)

This spec makes the **existing, implicit** tally-integrity contract explicit. It describes the
as-built behavior of `benchmark/tally_integrity.py`; it introduces **no behavior change**.

## Why

`check_sample_adequacy` verifies a top-level tally sums to the task total, but not that per-task
`rows` recount to the same tally or that `decisive_margin` matches the win/loss difference.
Making the contract explicit lets reviewers check tally-integrity changes against intent.

## User stories

1. **As a benchmark operator**, I can verify judge win/loss/tie accounting before trusting
   promotion or regression gates.
2. **As a CI maintainer**, I can gate on `check_tally_integrity()` with a stable pass/fail headline.
3. **As a reviewer**, optional-field semantics and malformed-input handling are written down.

## Acceptance criteria (EARS)

### Constants

- Valid row winner labels SHALL be exactly `challenger`, `baseline`, and `tie`.
- Tally dict keys SHALL be `challenger`, `baseline`, and `tie`.

### Numeric semantics (`_is_number`)

- Only non-boolean `int`/`float` values SHALL count as numeric.
- `bool` SHALL NOT be treated as numeric.

### Input coercion (`_dict`)

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Tally counts (`_tally_counts`)

- WHEN `tally` is not a `dict` THEN `_tally_counts` SHALL return `None`.
- WHEN any of the three tally keys is non-numeric THEN `_tally_counts` SHALL return `None`.
- WHEN all three keys are numeric THEN `_tally_counts` SHALL return int counts for each key.

### Row winner recount (`_count_row_winners`)

- WHEN `rows` is `None` THEN `_count_row_winners` SHALL return `None`.
- Unknown `winner` labels SHALL be ignored (not counted toward any bucket).
- Valid winners SHALL increment the matching tally bucket.

### Slice selection (`_integrity_slices`)

1. **Generalization** — WHEN `tuned` and `held_out` are dicts and `generalization_gap` is present
   THEN each partition with `scored_repos > 0` SHALL expand into scored slices (top-level
   `rows` on the partition, or each `per_repo` entry with `tasks > 0`).
2. **Multi** — WHEN `per_repo` is present THEN each dict entry with `tasks > 0` SHALL become a
   slice labeled `repo-{index}`.
3. **Single** — WHEN top-level `tasks > 0` THEN the artifact SHALL become one `run` slice.
4. **Fallback** — WHEN top-level `rows` is present (even with zero tasks) THEN the artifact SHALL
   become one `run` slice.
5. WHEN no slice qualifies THEN slice selection SHALL return `[]`.

Malformed `per_repo` and `rows` containers SHALL be logged and treated as empty (not raise).

### Per-slice checks (`_check_slice`)

Every selected slice SHALL evaluate, in order:

1. **`tally_present`** — `tally` carries numeric challenger/baseline/tie counts.
2. **`tasks_reported`** — `tasks` is a non-negative number.
3. **`tally_sums_to_tasks`** — the three tally counts sum to `tasks` when both tally and tasks are
   valid; otherwise the check SHALL fail with a missing-input detail.
4. **`rows_match_tasks`** — ONLY when the slice carries a `rows` key: usable row count equals
   `tasks`.
5. **`row_winners_match_tally`** — ONLY when the slice carries a `rows` key: winner labels in
   usable rows recount to the same tally; otherwise fail with missing-input detail.
6. **`decisive_margin_matches`** — ONLY when `decisive_margin` is present on the slice: it equals
   `challenger - baseline` when tally and margin are numeric; otherwise fail.

Slice labels SHALL prefix check names (`repo-0:`, `tuned:repo-1:`, etc.) except the lone `run`
slice, which uses unprefixed names.

### Gate entrypoint (`check_tally_integrity`)

- WHEN `result` is not a `dict` THEN the gate SHALL return `{"passed": false, "checks": [...]}`
  with a failing `artifact_shape` check (not raise).
- WHEN slice selection yields no slices THEN the gate SHALL fail `artifact_shape` with
  `"no scored replay slice with tally detail to verify"`.
- WHEN every check passes THEN `passed` SHALL be `true`; otherwise `false`.
- Each check row SHALL carry `name`, `passed`, and `detail`.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN a check row is not a `dict` THEN that row SHALL be skipped with a warning.
- `failed_checks(result)` SHALL return names of usable rows with `"passed": false`.
- WHEN `checks` is missing, empty, or only unusable rows THEN `failed_checks()` SHALL return `[]`.

### Integrity headline

- `integrity_headline(result)` SHALL return a one-line summary.
- IF no usable checks remain after sanitization THEN the headline SHALL read
  `tally integrity: no checks evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `CONSISTENT` and the check count.
- WHEN `result["passed"]` is false with usable checks THEN the headline SHALL include
  `INCONSISTENT` and failed check names.

### Pure evaluation

- The module SHALL perform no I/O in `check_tally_integrity()`.
- `check_tally_integrity()` SHALL NOT mutate its input dict.

## Out of scope

- Whether tally totals are *adequate* (`benchmark/sample_adequacy.py`).
- Per-row field completeness (`benchmark/row_integrity.py`).
- Changing runner tally semantics.

## Verification

- `tests/test_spec_030_tally_integrity.py` exercises each EARS block above.
- Broader CLI coverage remains in `tests/test_tally_integrity.py`.
