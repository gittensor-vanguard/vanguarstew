# Spec 030 — judge tally integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #901
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/sample_adequacy.py`](../../benchmark/sample_adequacy.py) (top-level tally sum),
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (decisive margin gate)

This spec makes the **existing, implicit** tally-integrity contract explicit. It describes the
as-built behavior of `benchmark/tally_integrity.py`; it introduces **no behavior change**.
Judge `tally`, per-task `rows`, and `decisive_margin` must agree internally.

## Why

`check_sample_adequacy` verifies a top-level tally sums to tasks but not that per-task rows
recount to the same tally or that `decisive_margin` matches wins minus losses. Making the
contract explicit lets reviewers check tally-integrity changes against intent.

## User stories

1. **As a benchmark operator**, I can verify judge tallies recount from per-task rows.
2. **As a CI maintainer**, I can gate on `check_tally_integrity()` with a stable headline.
3. **As a reviewer**, optional-field semantics and malformed-input handling are written down.

## Acceptance criteria (EARS)

### Winner vocabulary

- The module SHALL treat only `challenger`, `baseline`, and `tie` as valid `winner` labels when
  recounting rows (`_VALID_WINNERS`).

### Finite numeric semantics

- Only built-in `int`/`float` values SHALL count as numeric for tally and task counts (`_is_number`).
- `bool` SHALL NOT be treated as numeric (guarded before `isinstance(int/float)` coercion).

### Artifact shape

- WHEN `result` is not a `dict` THEN `check_tally_integrity(result)` SHALL return
  `{"passed": false, "checks": [...]}` with an `artifact_shape` check that fails (not raise).
- WHEN `result` has no scored replay slice with tally detail THEN the gate SHALL fail
  `artifact_shape`.

### Slice selection

- Single-repo artifacts with `tasks > 0` or top-level `rows` SHALL check the `run` slice.
- Multi-repo artifacts SHALL check each `per_repo` entry with `tasks > 0`.
- Generalization artifacts SHALL check each partition with `scored_repos > 0` and scored
  per-repo or top-level rows; check names SHALL be prefixed with `{partition}:` or
  `{partition}:repo-{index}:`.
- Slices with `tasks == 0` SHALL NOT be selected.

### Per-slice checks

For each selected slice, the gate SHALL always report:

1. `tally_present` — `tally` carries numeric `challenger`, `baseline`, and `tie` counts;
2. `tasks_reported` — `tasks` is a non-negative number;
3. `tally_sums_to_tasks` — the three tally counts sum to `tasks`.

WHEN the slice carries a `rows` key, the gate SHALL additionally report:

4. `rows_match_tasks` — usable row count equals `tasks`;
5. `row_winners_match_tally` — winner labels in `rows` recount to the same `tally`.

WHEN the slice carries a `decisive_margin` key, the gate SHALL additionally report:

6. `decisive_margin_matches` — `decisive_margin` equals `challenger - baseline`.

Missing optional keys (`rows`, `decisive_margin`) SHALL NOT emit the corresponding checks.

### Tally and container robustness

- WHEN `tally` is not a dict or any tally field is non-numeric THEN `_tally_counts()` SHALL
  return `None`.
- WHEN `rows` or `per_repo` is not a list THEN the container helper SHALL log a warning and
  treat the container as empty or malformed (not raise).
- WHEN a `rows` row is not a dict THEN that row SHALL be skipped with a warning.
- WHEN a `per_repo` row is not a dict THEN that row SHALL be skipped silently (filtered out).
- Unknown `winner` labels in rows SHALL be ignored when recounting (not counted toward any
  tally bucket).

### Gate result shape

- `check_tally_integrity()` SHALL return `{"passed", "checks"}` where `passed` is `True` only
  when every check passes.

### Malformed gate-result robustness

- `_check_rows_list(checks)` SHALL return `[]` for `None`, empty lists, and non-list containers
  (including tuples) after logging a warning for non-lists.
- Non-dict check rows SHALL be skipped with a warning.
- `failed_checks()` and `integrity_headline()` SHALL use sanitized rows only and never raise.

### Integrity headline

- WHEN `passed` is `True` THEN `integrity_headline()` SHALL report `CONSISTENT` with the
  sanitized check count.
- WHEN `passed` is `False` THEN `integrity_headline()` SHALL report `INCONSISTENT` with failed
  check names from sanitized rows.
- WHEN no usable check rows remain THEN `integrity_headline()` SHALL return
  `"tally integrity: no checks evaluated"`.

### Pure evaluation

- `check_tally_integrity()` SHALL NOT mutate its input and SHALL perform no I/O.
