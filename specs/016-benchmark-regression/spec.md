# Spec 016 — candidate-vs-baseline regression gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #765
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/regression.py`](../../benchmark/regression.py) (this gate),
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (Spec 014, the sibling *fixed-floor* gate),
  [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`, the composite this gate compares),
  [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (`_disagreement_rate_from_telemetry`, the shared order-disagreement recompute),
  [`scripts/regression.py`](../../scripts/regression.py) (CI entrypoint)

This spec makes the **existing, implicit** regression-gate contract explicit. It describes the
as-built behavior of `benchmark/regression.py`; it introduces **no behavior change**.

## Why

`check_promotion` (Spec 014) gates a run against a *fixed* floor, and `compare_eval` *reports* the
diff between two artifacts, but neither answers "did **this** run get worse than the **last accepted**
run?" — a moving floor that tracks the current best. `check_regression` turns that before/after
comparison into a reproducible pass/fail decision: a candidate is safe to accept only when it does
not drop the headline composite by more than `max_composite_drop` and does not make the pairwise
judge materially less stable (order-`disagreement_rate` rising by more than
`max_disagreement_increase`). The companion `scripts/regression.py` exits non-zero when a regression
is found, so a run can be gated against the previous baseline the way `--fail-under` gates against a
constant.

## User stories

1. **As a benchmark operator**, I can gate a candidate run against the last accepted baseline so a
   composite drop or a rise in judge instability blocks acceptance.
2. **As a CI maintainer**, I can log a stable `regression_headline()` string alongside the JSON
   result and exit non-zero via `scripts/regression.py` when a regression is found.
3. **As a reviewer**, the malformed-input handling, the generalization-partition disagreement
   summation, the stale-telemetry recompute, the inclusive bounds, fail-closed semantics, and every
   headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN an artifact (`candidate` or `baseline`) is not a `dict` THEN the gate SHALL treat it as `{}`
  and evaluate (not raise); a malformed artifact SHALL simply fail the checks it cannot satisfy.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`)

- `_is_number` SHALL be true for built-in `int` and `float` values.
- `bool` SHALL NOT be treated as a number (`_is_number(True)` is `False`).
- Every non-`int`/`float` value SHALL be non-numeric.

### Rounding (`_round`)

- WHEN the value is a number THEN `_round` SHALL return `round(float(value), 3)`.
- OTHERWISE (including `bool` and non-numeric values) `_round` SHALL return `None`.

### Compared composite (`headline_score`)

- `baseline_composite` and `candidate_composite` SHALL be `benchmark.trend.headline_score(artifact)`
  — a single-repo composite, the tuned partition of a generalization run, or `None` for an unscored,
  errored, or malformed run. The unscored-placeholder and tuned-partition rules live in
  `headline_score`; this gate inherits them rather than re-implementing them.

### Order-disagreement resolution

- `_flat_disagreement(artifact)` SHALL prefer `judge_order_stats` over `judge_report`, delegate each
  to `_disagreement_rate_from_telemetry`, and return the first rate found, or `None` when neither
  telemetry block yields a rate.
- `_partition_disagreement_counts(part)` SHALL read one partition, preferring `judge_order_stats`
  then `judge_report`; it SHALL use a numeric `dual_order_tasks`, else derive it as
  `agree + disagree + tie` when all three are integers, else treat it as absent; it SHALL read the
  disagreement count from `disagree` or, absent that, `disagreements`; and it SHALL return
  `(disagreements, dual_order_tasks)` only when `dual_order_tasks` is an integer `> 0` and the
  disagreement count is an integer `>= 0`, otherwise `None`.
- `_disagreement(artifact)` — WHEN the artifact carries both a `tuned` and a `held_out` key THEN it
  SHALL sum both partitions' disagreement and dual-order counts and return
  `total_disagree / total_dual` (or `None` when the summed dual-order total is `0`), mirroring the
  `disagreement_outlook` partition fix (#1037 / #1041); OTHERWISE it SHALL return the flat rate.

### Gate evaluation (`check_regression`)

The result SHALL always include: `passed`, `checks`, `baseline_composite`, `candidate_composite`,
`composite_delta`, `disagreement_delta`, `max_composite_drop`, `max_disagreement_increase`.

- `checks` SHALL always report exactly three rows, in order: `both_scored`,
  `no_composite_regression`, `no_judge_instability_increase`; each row is `{name, passed, detail}`
  with a `bool` `passed`.
- `both_scored` SHALL pass iff both `baseline_composite` and `candidate_composite` are not `None`.
- `composite_delta` SHALL be `_round(candidate_composite - baseline_composite)` when both are scored,
  else `None`; `no_composite_regression` SHALL pass iff both are scored AND
  `composite_delta >= -max_composite_drop` (inclusive — the delta is rounded to 3 places first so a
  drop exactly equal to the tolerance is not tipped over it by floating-point noise).
- `disagreement_delta` SHALL be `_round(candidate_disagreement - baseline_disagreement)` when both
  runs report a rate, else `None`. WHEN it is `None` (at least one run judged single-order) THEN
  `no_judge_instability_increase` SHALL pass vacuously; OTHERWISE it SHALL pass iff
  `disagreement_delta <= max_disagreement_increase` (inclusive).
- `passed` SHALL be `True` iff every check passed.
- The default thresholds SHALL be `max_composite_drop = 0.02` (`DEFAULT_MAX_COMPOSITE_DROP`) and
  `max_disagreement_increase = 0.1` (`DEFAULT_MAX_DISAGREEMENT_INCREASE`), and both SHALL be
  overridable per call.

### Checks-row sanitization (`_check_rows_list`)

- `None` (absent key) and an empty list SHALL yield `[]` silently.
- A non-list container (scalar, dict, tuple, range, string, …) SHALL be warned and treated as empty
  (never coerced or iterated).
- A row that is not a `dict`, or a row missing `name` or `passed`, or whose `name` is not a `str`, or
  whose `passed` is not exactly a `bool`, SHALL each be skipped with a warning.
- WHEN a non-empty `checks` yields no usable rows THEN a warning SHALL be logged.

### Failed checks (`failed_checks`)

- `failed_checks(result)` SHALL return the `name` of each usable row whose `passed` is falsey, routed
  through `_check_rows_list` so a malformed `checks` container or unusable rows are skipped rather
  than raising.

### Regression headline (`regression_headline`)

- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be `regression: no checks evaluated`.
- WHEN `passed` is truthy THEN the headline SHALL be
  `regression: OK (composite {baseline_composite} -> {candidate_composite}, delta {composite_delta})`.
- OTHERWISE the headline SHALL be
  `regression: BLOCKED ({failed}/{total} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_regression()` SHALL NOT mutate either input artifact.

## Verification

- `tests/test_spec_016_regression.py` exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_regression.py`.
