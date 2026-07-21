# Spec 069 — generalization gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1926
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (`_partition_error`,
  the shared per-repo error scan this reuses), [`benchmark/component_floor.py`](../../benchmark/component_floor.py)
  (sibling gate, same `_composite`/`_check_rows_list` shape), [`benchmark/trend.py`](../../benchmark/trend.py)
  (`headline_score`, the unscored-placeholder convention), [`benchmark/coverage.py`](../../benchmark/coverage.py)
  (`_repo_counts`, the `tasks: 0` scored-vs-skipped convention)

This spec makes the **existing, implicit** generalization-gate contract explicit. It describes the
as-built behavior of `benchmark/generalization_gate.py`; it introduces **no behavior change**.

## Why

M3/M4 ask the maintainer agent to hold up on *diverse, unseen* repos, not just the ones it tuned
on. `run_multi_replay --generalization` reports a `tuned` partition, a `held_out` partition, and a
`generalization_gap`, but nothing turns that into a pass/fail decision — a run that tuned to 0.70
and collapsed to 0.40 on held-out repos flows through unflagged. `check_generalization` gates that:
both partitions must score, the held-out set must be broad enough, and the tuned-minus-held-out
drop must be within tolerance. The gap is **recomputed** from the two composites rather than
trusting a possibly-stale `generalization_gap` field. Making the contract explicit lets reviewers
check changes against intent and pins that it uses the shared, non-diverging `_is_number`
finiteness guard and `_partition_error` scan exactly like its siblings.

## User stories

1. **As a benchmark operator**, I can block promotion of a run that overfit its tuned repos.
2. **As a CI maintainer**, I can gate on `scripts/generalization_gate.py` and log a stable
   `generalization_headline()` string.
3. **As a reviewer**, every helper edge case (`_composite` / `_scored_repos` / `_partition_error`,
   including NaN/inf, missing keys, non-dict `per_repo` entries, and the unscored
   `composite_mean == 0.0` placeholder) and headline branch is written down (addressing the
   incompleteness class of rejection seen on Specs 057/059 and PR #1911).

## Constants

- `DEFAULT_MAX_GAP` SHALL be `0.1`.
- `DEFAULT_MIN_HELD_OUT_REPOS` SHALL be `3`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Numeric helper (`_is_number`, `_num`)

- `_is_number(value)` SHALL be true only for **non-boolean** `int`/`float` values that are finite.
- A `bool` SHALL be false (`bool` is an `int` subclass, excluded explicitly); `NaN`, `inf`, `-inf`
  SHALL be false; an oversized `int` whose `math.isfinite` raises `OverflowError` SHALL be false;
  a non-numeric type SHALL be false.
- `_num(value)` SHALL be `f"{value:.3f}"` when `_is_number(value)`, else the literal `"n/a"` — a
  fixed 3-decimal, platform-independent format.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Partition composite (`_composite`)

- `_composite(partition)` SHALL coerce a non-dict `partition` to `{}` (returning `None`).
- WHEN the partition carries `scored_repos` that is `_is_number` and falsy (`0`) THEN it SHALL
  return `None` — a partition that scored no repos reports a placeholder `composite_mean` of `0.0`
  (an average over an empty list), an infra outcome that must not masquerade as a real `0.0` and
  produce a spuriously-negative gap.
- OTHERWISE it SHALL return `composite_mean` when `_is_number(composite_mean)`, else `None`
  (so a missing key, `NaN`, `inf`, or non-numeric composite yields `None`).
- A partition with no `scored_repos` key SHALL keep a genuine `0.0` composite.

### Held-out repo count (`_scored_repos`)

- `_scored_repos(partition)` SHALL return the explicit `scored_repos` when `_is_number`.
- OTHERWISE, WHEN `per_repo` is a list THEN it SHALL return `len(per_repo)` minus the count of
  entries that are dicts with `_is_number(tasks)` and `tasks == 0` — the `coverage._repo_counts`
  scored-vs-skipped convention (a held-out repo skipped as too-small is not counted). A `per_repo`
  entry that is not a dict, or a dict with no `tasks`, SHALL NOT be treated as skipped.
- WHEN `per_repo` is absent or not a list (and no numeric `scored_repos`) THEN it SHALL return
  `None`.

### Partition error scan (`_partition_error`)

- `_partition_error(partition)` (from `benchmark.acceptance`) SHALL surface the partition's
  top-level `error`, else the first `per_repo[i].error`, else the first `per_repo` entry that is a
  non-empty **string** (a corrupt row), else `None`. A non-dict partition SHALL yield `None`.
- Both `tuned` and `held_out` partitions SHALL be scanned independently for the `no_partition_error`
  check.

### Gate result (`check_generalization`)

Every result mapping SHALL carry `passed`, `checks`, `tuned_composite`, `held_out_composite`,
`gap`, `held_out_repos`, `max_gap`, `min_held_out_repos`. The `checks` list SHALL always be the
four rows, in order: `has_partitions`, `no_partition_error`, `enough_held_out_repos`,
`gap_within_tolerance`.

- `tuned_composite` / `held_out_composite` SHALL be `_composite` of the respective partitions.
- `gap` SHALL be `round(tuned - held, 3)` when **both** composites are non-`None`, else `None`.
- `has_partitions` SHALL pass only when both composites are non-`None`; detail SHALL be
  `f"tuned composite {_num(tuned)}, held-out composite {_num(held)}"` when both exist, else
  `"a composite is missing from the tuned or held-out partition"`.
- `no_partition_error` SHALL pass only when neither partition errors; failing detail SHALL be
  `f"partition error(s): tuned={tuned_err!r}, held_out={held_err!r}"`, passing detail
  `"both partitions completed without error"`.
- `enough_held_out_repos` SHALL pass only when `_is_number(held_repos)` and
  `held_repos >= min_held_out_repos`; detail SHALL be
  `f"{held_repos} held-out repo(s) >= {min_held_out_repos}"` when numeric, else
  `"held-out repo count unavailable"`.
- `gap_within_tolerance` SHALL pass only when `gap is not None` and `gap <= max_gap` (a held-out
  score that **exceeds** tuned is a non-positive gap and always within tolerance); detail SHALL be
  `f"tuned - held-out = {_num(gap)} <= {max_gap}"` when comparable, else
  `"cannot compare the partitions"`.
- `passed` SHALL be `all(c["passed"] for c in checks)`.
- `held_out_repos` in the mapping SHALL be the count when `_is_number`, else `None`; `max_gap` and
  `min_held_out_repos` SHALL echo the caller's values.
- WHEN `result` is not a `dict` THEN it SHALL be coerced to `{}` and every check SHALL fail rather
  than raising.

### Checks-row sanitation (`_check_rows_list`)

- `None` `checks` SHALL yield `[]`; a non-list `checks` SHALL log a warning and yield `[]`.
- A row SHALL be skipped (with a warning) when it is not a `dict`, is missing `name`/`passed`, has a
  non-`str` `name`, or a `passed` whose type is not `bool` (so a numpy/`int` truthy value is
  rejected).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy,
  over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `generalization_headline` SHALL be exactly
  `generalization: no checks evaluated`. A non-dict argument SHALL yield the same string.
- WHEN `result.passed` is truthy THEN it SHALL be
  `f"generalization: GENERALIZES (tuned {_num(tuned_composite)} -> held-out {_num(held_out_composite)}, gap {_num(gap)})"`.
- OTHERWISE it SHALL be
  `f"generalization: OVERFIT ({f}/{n} checks failed: {names})"`, where `names` is the failed check
  names joined by `", "`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_generalization()` SHALL NOT mutate its input.

## Out of scope

- The upstream `generalization_gap` computation and the `run_multi_replay --generalization`
  partitioning.
- The component-floor gate (`component_floor.py`) and the adoption gate (`improvement.py`).
- Changing any default threshold or the `scored_repos` / `tasks: 0` conventions.

## Verification

- `tests/test_spec_069_generalization_gate.py` exercises each EARS block above, pinning **literal**
  expected detail and headline strings (with concrete, platform-independent numeric inputs) rather
  than re-deriving them from the module, and covers constants, `_is_number` (bool/NaN/inf/
  oversized-int), `_composite` (placeholder `0.0`, NaN, missing key, non-dict), `_scored_repos`
  (explicit count, `per_repo` `tasks: 0` exclusion, non-dict entry, non-list), both-partition
  `_partition_error`, the negative-gap (held-out exceeds tuned) case, checks-row sanitation, and
  every headline branch.
- Broader coverage (including the CLI) remains in `tests/test_generalization_gate.py`.
