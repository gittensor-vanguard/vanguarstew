# Spec 059 — composite score integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1690
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (per-row composite checks),
  [`benchmark/aggregate_integrity.py`](../../benchmark/aggregate_integrity.py) (multi-repo rollup),
  [`benchmark/blend_weights.py`](../../benchmark/blend_weights.py) (weight telemetry),
  [`benchmark/score.py`](../../benchmark/score.py) (`composite_score` definition)

This spec makes the **existing, implicit** score-integrity contract explicit. It describes the
as-built behavior of `benchmark/score_integrity.py`; it introduces **no behavior change**.

## Why

A replay artifact reports `composite_mean`, `composite_parts`, and `weights`, but nothing verifies
they agree with the weight-normalized blend. A corrupted or mis-assembled artifact would otherwise
pass through `compare_eval` / `trend` / the leaderboard as if it were real.

## User stories

1. **As a benchmark operator**, I can verify the headline composite matches its component blend
   before trusting promotion or regression gates.
2. **As a CI maintainer**, I can gate on `check_score_integrity()` with a stable pass/fail headline.
3. **As a reviewer**, weight resolution, generalization slicing, and malformed-input handling are
   written down.

## Acceptance criteria (EARS)

### Constants

- `DEFAULT_W_JUDGE` SHALL be `0.6`.
- `DEFAULT_W_OBJECTIVE` SHALL be `0.4`.
- `DEFAULT_TOLERANCE` SHALL be `0.002`.

### Numeric semantics (`_is_number`, `_round3`)

- Only **finite**, non-boolean `int`/`float` values SHALL count as numeric.
- `bool`, `NaN`, `Infinity`, and ints that overflow float SHALL NOT count as numeric.
- `_round3(value)` SHALL return `round(float(value), 3)` when `value` passes `_is_number`,
  otherwise `None`.

### Input coercion (`_dict`)

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Weight resolution (`_weights`)

- WHEN top-level `weights` carries numeric `judge` and `objective` THEN those SHALL be used.
- OTHERWISE WHEN the first usable `per_repo` dict entry carries numeric nested weights THEN those
  SHALL be used.
- OTHERWISE the gate SHALL fall back to `(DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)` and log a warning.
- Non-list / unusable `per_repo` entries SHALL be skipped with a warning (not raise).

### Expected blend (`_expected_composite`)

- The expected composite SHALL be the weight-normalized blend of the two component means,
  rounded to 3 decimal places.
- WHEN the weight sum is `0` THEN the divisor SHALL be `1.0` (no divide-by-zero).

### Scoring slices (`_scoring_slices`, `_partition_scored`)

1. **Generalization** — WHEN `tuned` and `held_out` are dicts and `generalization_gap` is present
   THEN each scored partition SHALL become a labeled slice (`tuned`, `held_out`).
2. A partition SHALL be scored WHEN `scored_repos` is a positive number, OR WHEN `scored_repos` is
   absent/non-numeric and `composite_mean` is numeric.
3. OTHERWISE the whole artifact SHALL be one `run` slice.
4. WHEN generalization yields no scored partitions THEN slice selection SHALL return `[]`.

### Per-slice checks (`_check_slice`)

Every selected slice SHALL evaluate, in order:

1. **`composite_numeric`** — `composite_mean` is numeric.
2. **`composite_in_range`** — `composite_mean` is in `[0, 1]`.
3. **`components_present`** — `composite_parts` carries numeric `judge_mean` and `objective_mean`.
4. **`components_in_range`** — both component means are in `[0, 1]`.
5. **`blend_consistent`** — WHEN composite and components are present THEN
   `|composite - expected| <= tolerance`; OTHERWISE the check SHALL fail closed.

Generalization slice labels SHALL prefix check names (`tuned:`, `held_out:`); the lone `run`
slice uses unprefixed names.

### Gate entrypoint (`check_score_integrity`)

Every result SHALL include: `passed`, `checks`, `tolerance`.

- WHEN `result` is not a `dict` THEN the gate SHALL fail `artifact_shape` (not raise).
- WHEN slice selection yields no slices THEN the gate SHALL fail `artifact_shape` with
  `"no scored partition to verify (generalization partitions unscored)"`.
- WHEN every check passes THEN `passed` SHALL be `true`; otherwise `false`.
- Each check row SHALL carry `name`, `passed`, and `detail`.
- `tolerance` SHALL default to `DEFAULT_TOLERANCE` and be overridable.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN a check row is not a usable `{name: str, passed: bool}` dict THEN that row SHALL be skipped
  with a warning.
- `failed_checks(result)` SHALL return names of usable rows with `"passed": false`.

### Integrity headline

- WHEN no usable checks remain THEN the headline SHALL be exactly:
  `score integrity: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `score integrity: CONSISTENT ({n} checks passed)`.
- OTHERWISE the headline SHALL be:
  `score integrity: INCONSISTENT ({failed}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O in `check_score_integrity()`.
- `check_score_integrity()` SHALL NOT mutate its input dict.

## Out of scope

- Per-row composite recomputation (`benchmark/row_integrity.py`).
- Multi-repo rollup math (`benchmark/aggregate_integrity.py`).
- Changing `composite_score` blend semantics in `benchmark/score.py`.

## Verification

- `tests/test_spec_059_score_integrity.py` exercises each EARS block above.
- Broader coverage (including CLI) remains in `tests/test_score_integrity.py`.
