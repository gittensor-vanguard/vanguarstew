# Spec 014 — challenger promotion gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #763
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/promotion.py`](../../benchmark/promotion.py) (this gate),
  [`benchmark/regression.py`](../../benchmark/regression.py) (sibling moving-floor gate),
  [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`, the tuned-partition rule this gate mirrors),
  [`scripts/promotion.py`](../../scripts/promotion.py) (CI entrypoint)

This spec makes the **existing, implicit** promotion-gate contract explicit. It describes the
as-built behavior of `benchmark/promotion.py`; it introduces **no behavior change**.

## Why

A benchmark exists to decide *whether one agent is good enough to prefer over the reference*, and
M2 acceptance is explicit that "an agent that merely restates a memorized outcome does **not**
win." `run_eval` reports the raw numbers (`composite_mean`, `decisive_margin`, judge stats), but
the *decision* — is this run good enough to promote? — is otherwise made by eye. `check_promotion`
turns that decision into a reproducible pass/fail gate so an under-performing or memorized-tie run
fails closed instead of being waved through.

## User stories

1. **As a benchmark operator**, I can gate a run on a composite floor and a decisive win before
   promoting the challenger over the reference agent.
2. **As a CI maintainer**, I can log a stable `promotion_headline()` string alongside the JSON
   result and exit non-zero via `scripts/promotion.py` when the gate holds.
3. **As a reviewer**, the malformed-input handling, the tuned-partition rule for generalization
   artifacts, the unscored-placeholder guard, fail-closed semantics, and every headline branch are
   written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the `result` is not a `dict` THEN `check_promotion(result)` SHALL treat it as `{}` and
  evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`)

- `_is_number` SHALL be true for built-in `int` and `float` values.
- `bool` SHALL NOT be treated as a number (`_is_number(True)` is `False`).
- Every non-`int`/`float` value SHALL be non-numeric.

### Evaluated partition (`_promotion_source`)

- WHEN both `tuned` and `held_out` are `dict`s THEN the gate SHALL evaluate the **tuned**
  partition (a `run_generalization_report` nests every scored field under `tuned`/`held_out` with
  no top-level `composite_mean`/`judge_report`; its headline is the tuned partition, mirroring
  `benchmark.trend.headline_score`).
- OTHERWISE (either key missing or non-`dict`) the gate SHALL evaluate the top-level `result`.
- The gate SHALL read `composite_mean`, the decisive margin, and the disagreement rate from the
  evaluated partition, but SHALL treat a top-level **or** partition-level `error` as an incomplete
  run.

### Scored composite (`_scored_composite`)

- WHEN `composite_mean` is not a number THEN `_scored_composite` SHALL return `None`.
- WHEN `scored_repos` is a number and falsey (`0`) THEN `_scored_composite` SHALL return `None`
  — the unscored multi-repo placeholder (`composite_mean: 0.0` averaged over an empty list) is not
  a real score.
- OTHERWISE `_scored_composite` SHALL return the composite. A single-repo run (no `scored_repos`
  key) SHALL keep its real composite, including a genuine `0.0`; a `bool` `scored_repos` (not a
  number) SHALL NOT be read as the placeholder, so the run keeps its composite.

### Decisive margin (`_decisive_margin`)

- WHEN `decisive_margin` is a number THEN `_decisive_margin` SHALL return it.
- OTHERWISE WHEN a top-level `tally` carries numeric `challenger` and `baseline` THEN it SHALL
  return `challenger - baseline`.
- OTHERWISE WHEN `judge_report` carries numeric `wins` and `losses` THEN it SHALL return
  `wins - losses` (so a multi-repo / generalization run, which has no top-level margin or tally,
  is not held on `beats_baseline` for lack of a top-level margin).
- OTHERWISE `_decisive_margin` SHALL return `None`.

### Gate evaluation (`check_promotion`)

The result SHALL always include: `passed`, `checks`, `composite_mean`, `decisive_margin`,
`disagreement_rate`, `min_composite`, `min_decisive_margin`, `max_disagreement`.

- `checks` SHALL always report exactly four rows, in order: `run_completed`, `composite_floor`,
  `beats_baseline`, `judge_trustworthy`; each row is `{name, passed, detail}` with a `bool`
  `passed`.
- `run_completed` SHALL pass iff there is no `error` AND `_scored_composite` is not `None`.
- `composite_floor` SHALL pass iff the composite is not `None` AND `composite >= min_composite`
  (inclusive).
- `beats_baseline` SHALL pass iff the decisive margin is a number AND `margin >= min_decisive_margin`
  (inclusive).
- WHEN the disagreement rate is `None` (a single-order judge, no instability signal) THEN
  `judge_trustworthy` SHALL pass; OTHERWISE it SHALL pass iff the rate is a number AND
  `rate <= max_disagreement` (inclusive), and a non-numeric rate SHALL fail it.
- `passed` SHALL be `True` iff every check passed.
- The default thresholds SHALL be `min_composite = 0.5` (`DEFAULT_MIN_COMPOSITE`),
  `min_decisive_margin = 1` (`DEFAULT_MIN_DECISIVE_MARGIN`), and `max_disagreement = 0.5`
  (`DEFAULT_MAX_DISAGREEMENT`), and all three SHALL be overridable per call.

### Checks-row sanitization (`_check_rows_list`)

- `None` (absent key) and an empty list SHALL yield `[]` silently.
- A non-list container (scalar, dict, tuple, range, string, …) SHALL be warned and treated as
  empty (never coerced or iterated).
- A row that is not a `dict`, or a row missing `name` or `passed`, SHALL each be skipped with a
  warning.
- WHEN a non-empty `checks` yields no usable rows THEN a warning SHALL be logged.

### Failed checks (`failed_checks`)

- `failed_checks(result)` SHALL return the `name` of each usable row whose `passed` is falsey,
  routed through `_check_rows_list` so a malformed `checks` container or unusable rows are skipped
  rather than raising.

### Promotion headline (`promotion_headline`)

- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be `promotion: no checks evaluated`.
- WHEN `passed` is truthy THEN the headline SHALL be
  `promotion: PROMOTE (composite {composite_mean}, decisive_margin {decisive_margin})`.
- OTHERWISE the headline SHALL be
  `promotion: HOLD ({failed}/{total} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_promotion()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_014_promotion.py` exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_promotion.py`.
