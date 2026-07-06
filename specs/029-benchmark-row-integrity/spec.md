# Spec 029 — per-task row integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #900
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (headline blend checks),
  [`benchmark/aggregate_integrity.py`](../../benchmark/aggregate_integrity.py) (cross-repo means)

This spec makes the **existing, implicit** row-integrity contract explicit. It describes the
as-built behavior of `benchmark/row_integrity.py`; it introduces **no behavior change**.
Per-task `rows` must agree with headline aggregates and the composite blend formula.

## Why

`check_score_integrity` verifies headline component blends but not that each row's `composite`
was computed correctly or that headline means equal row averages. Making the contract explicit
lets reviewers check row-integrity changes against intent.

## User stories

1. **As a benchmark operator**, I can verify per-task composites match the blend formula before
   trusting replay artifacts.
2. **As a CI maintainer**, I can gate on `check_row_integrity()` with a stable headline.
3. **As a reviewer**, finite-number semantics, weight resolution, and malformed-input handling
   are written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_TOLERANCE = 0.002` as the default comparison bound for
  `check_row_integrity(result, tolerance=...)`.
- The module SHALL expose `DEFAULT_W_JUDGE = 0.6` and `DEFAULT_W_OBJECTIVE = 0.4` as the
  fallback blend weights when a slice carries no usable `weights` dict.

### Finite numeric semantics

- Only built-in `int`/`float` values SHALL count as numeric for row checks (`_is_number`).
- `bool` SHALL NOT be treated as numeric (guarded before `isinstance(int/float)` coercion).

### Artifact shape

- WHEN `result` is not a `dict` THEN `check_row_integrity(result)` SHALL return
  `{"passed": false, "checks": [...], "tolerance": ...}` with an `artifact_shape` check that
  fails (not raise).
- WHEN `result` has no scored replay slice with per-task `rows` THEN the gate SHALL fail
  `artifact_shape` with detail about missing slices.

### Slice selection

- Single-repo artifacts with top-level `rows` SHALL check the `run` slice.
- Multi-repo artifacts SHALL check each `per_repo` entry with `tasks > 0` and a `rows` key.
- Generalization artifacts SHALL check each partition (`tuned`, `held_out`) with
  `scored_repos > 0` and scored per-repo or top-level rows; check names SHALL be prefixed
  with `{partition}:` or `{partition}:repo-{index}:`.

### Weight resolution

- WHEN a slice carries a `weights` dict with finite numeric `judge` and `objective` keys THEN
  those weights SHALL be used for row composite verification.
- WHEN top-level weights are absent THEN the gate SHALL consult nested `per_repo` entries for
  the first usable weights dict.
- WHEN no usable weights are found THEN `DEFAULT_W_JUDGE` / `DEFAULT_W_OBJECTIVE` SHALL apply.

### Per-slice checks

For each selected slice, the gate SHALL report:

1. `rows_present` — at least one usable dict row in `rows`;
2. `row_composites_consistent` — each row's `composite` matches
   `composite_score(winner, objective, w_judge, w_objective)` within `tolerance`;
3. `composite_mean_matches_rows` — headline `composite_mean` equals the rounded row mean
   within `tolerance`;
4. `judge_mean_matches_rows` — `composite_parts.judge_mean` equals the rounded row judge
   component mean within `tolerance`;
5. `objective_mean_matches_rows` — `composite_parts.objective_mean` equals the rounded row
   objective anchor mean within `tolerance`.

### Row and container robustness

- WHEN `rows` or `per_repo` is not a list THEN the container helper SHALL log a warning and
  treat the container as empty (not raise).
- WHEN a `rows` row is not a dict THEN that row SHALL be skipped with a warning.
- WHEN a `per_repo` row is not a dict THEN that row SHALL be skipped silently (filtered out).

### Gate result shape

- `check_row_integrity()` SHALL return `{"passed", "checks", "tolerance"}` where `passed` is
  `True` only when every check passes.

### Malformed gate-result robustness

- `_check_rows_list(checks)` SHALL return `[]` for `None`, empty lists, and non-list containers
  (including tuples) after logging a warning for non-lists.
- Dict rows missing `name` or `passed` SHALL be skipped with a warning.
- `failed_checks()` and `integrity_headline()` SHALL use sanitized rows only and never raise.

### Integrity headline

- WHEN `passed` is `True` THEN `integrity_headline()` SHALL report `CONSISTENT` with the
  sanitized check count.
- WHEN `passed` is `False` THEN `integrity_headline()` SHALL report `INCONSISTENT` with failed
  check names from sanitized rows.
- WHEN no usable check rows remain THEN `integrity_headline()` SHALL return
  `"row integrity: no checks evaluated"`.

### Pure evaluation

- `check_row_integrity()` SHALL NOT mutate its input and SHALL perform no I/O.
