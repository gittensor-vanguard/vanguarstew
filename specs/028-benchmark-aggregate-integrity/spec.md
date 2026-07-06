# Spec 028 — multi-repo aggregate integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #888
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (per-repo row checks),
  [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (headline blend checks)

This spec makes the **existing, implicit** aggregate-integrity contract explicit. It describes the
as-built behavior of `benchmark/aggregate_integrity.py`; it introduces **no behavior change**.
Multi-repo artifacts average per-repo scores into a headline — that cross-repo arithmetic must be
written down and verified.

## Why

Per-repo integrity gates verify slices inside each repo; nothing verifies the cross-repo headline
equals the unweighted mean of scored `per_repo` entries. Making the contract explicit lets
reviewers check aggregate-integrity changes against intent.

## User stories

1. **As a benchmark operator**, I can verify a multi-repo artifact's headline means match its
   per-repo rows before trusting leaderboard output.
2. **As a CI maintainer**, I can gate on `check_aggregate_integrity()` with a stable headline.
3. **As a reviewer**, finite-number semantics and malformed-input handling are written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_TOLERANCE = 0.0` as the default comparison bound for
  `check_aggregate_integrity(result, tolerance=...)`.

### Finite numeric semantics

- Only finite built-in `int`/`float` values SHALL count as numeric for aggregate checks.
- `bool`, `NaN`, `inf`, and numpy scalar types SHALL NOT be treated as numeric scores or counts.

### Artifact shape

- WHEN `result` is not a `dict` THEN `check_aggregate_integrity(result)` SHALL return
  `{"passed": false, "checks": [...], "tolerance": ...}` with an `artifact_shape` check that
  fails (not raise).
- WHEN `result` has no multi-repo slice with a `per_repo` list THEN the gate SHALL fail
  `artifact_shape` with detail about missing slices.

### Slice selection

- Single-repo artifacts (no `per_repo` list) SHALL fail `artifact_shape`.
- Generalization artifacts SHALL check each partition (`tuned`, `held_out`) that carries a
  `per_repo` list; check names SHALL be prefixed with `{partition}:`.

### Per-slice checks

For each selected slice, the gate SHALL report:

1. `per_repo_present` — at least one usable dict row in `per_repo`;
2. `scored_repos_matches` — headline `scored_repos` equals repos with `tasks > 0`;
3. `skipped_matches` — headline `skipped` equals `len(per_repo) - scored_count`;
4. `repos_count_matches` — when `repos` is present, it equals `len(per_repo)`;
5. `scored_composites_reported` — every scored repo carries a finite `composite_mean`;
6. `composite_mean_matches_repos` — headline `composite_mean` equals the rounded per-repo mean
   within `tolerance`;
7. `judge_mean_matches_repos` / `objective_mean_matches_repos` — when `composite_parts` is a dict,
   component means equal rounded per-repo component means within `tolerance`.

### Per-repo container robustness

- WHEN `per_repo` is not a list THEN `_per_repo_list()` SHALL log a warning and treat the
  container as empty (not raise).
- WHEN a `per_repo` row is not a dict THEN that row SHALL be skipped with a warning.

### Gate result shape

- `check_aggregate_integrity()` SHALL return `{"passed", "checks", "tolerance"}` where `passed` is
  `True` only when every check passes.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN a check row is not a dict, or is missing `name`/`passed`, or has non-string `name`, or has
  non-bool `passed` THEN that row SHALL be skipped with a warning.
- `failed_checks(result)` SHALL return names of usable rows with `"passed": false`.
- WHEN `checks` is missing, empty, or only unusable rows THEN `failed_checks()` SHALL return `[]`.

### Integrity headline

- `integrity_headline(result)` SHALL return a one-line summary.
- IF no usable checks remain after sanitization THEN the headline SHALL read
  `aggregate integrity: no checks evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `CONSISTENT`.
- WHEN `result["passed"]` is false with usable checks THEN the headline SHALL include
  `INCONSISTENT` and failed check names.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_aggregate_integrity()` SHALL NOT mutate its input dict.

## Out of scope

- Per-task row recomputation (`benchmark/row_integrity.py`).
- Headline blend of components (`benchmark/score_integrity.py`).
- Changing `run_multi_replay` aggregation semantics.

## Verification

- `tests/test_spec_028_aggregate_integrity.py` (this PR) exercises each EARS block above.
- Broader CLI coverage remains in `tests/test_aggregate_integrity.py`.
