# Spec 071 — judge robustness gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1914
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (the gate under test),
  [`benchmark/disagreement_outlook.py`](../../benchmark/disagreement_outlook.py) (the same
  disagreement telemetry, reported not gated),
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (the promotion decision),
  [`scripts/judge_gate.py`](../../scripts/judge_gate.py) (the CI entry point)

This spec makes the **existing, implicit** judge-robustness contract explicit. It describes the
as-built behavior of `benchmark/judge_gate.py`; it introduces **no behavior change**. The module is
self-contained (its only import is `math`); this spec references no other module's contract.

## Why

M2/M3 acceptance leans on judge robustness — pairwise judging, dual-order consistency, disagreement
tracking. A composite score is only as trustworthy as the judge behind it: a run judged in a single
presentation order, or whose two orders disagreed on a large fraction of tasks, has a shaky win/loss
record and a shaky `judge_mean`. `check_judge` turns the reported judge stats into a reproducible
pass/fail gate, on the evaluated (top-level, or `tuned` for a generalization) partition.

## User stories

1. **As a CI maintainer**, I can gate a run's verdicts on `scripts/judge_gate.py` before trusting
   them, and log a stable `judge_headline()` ROBUST/SHAKY line.
2. **As a benchmark operator**, I can trust ROBUST means the run judged both orders, on a meaningful
   sample, with a low order-disagreement rate recomputed from authoritative counts (a stale rate
   field cannot false-pass).
3. **As a reviewer**, every non-finite / missing / incoherent-count / generalization / headline
   branch is written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MAX_DISAGREEMENT` SHALL be `0.3`, `DEFAULT_MIN_DUAL_ORDER_TASKS` SHALL be `2`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Numeric / type helpers

- `_is_number(value)` SHALL be true only for a non-boolean `int`/`float` whose `float(value)` is
  finite; a `NaN`/`inf` SHALL be false, and a `TypeError`/`OverflowError` (e.g. an oversized `int`)
  SHALL yield false, never raise.
- `_is_int(value)` SHALL be true only for a non-boolean `int`.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_passed(value)` SHALL be true only for a native `bool` (`type(value) is bool`) or a `numpy`
  scalar boolean (`type(value).__name__` in `bool_`/`bool8`/`bool`); an `int` `0`/`1` and a `bool`
  subclass SHALL be false.
- `_check_row_field("name", value)` SHALL require a non-empty `str`; `_check_row_field("passed",
  value)` SHALL require `_is_passed`.

### Dual-order task count (`_dual_order_tasks`)

- It SHALL return the first `_is_number` `dual_order_tasks` found under `result["judge_report"]`
  then `result["judge_order_stats"]`, otherwise `None`.

### Disagreement rate (`_disagreement_rate_from_telemetry`, `_disagreement_rate`)

- `_disagreement_rate_from_telemetry(telemetry)` SHALL determine `dual` as the `_is_number`
  `dual_order_tasks`, else `agree + disagree + tie` when all three are `_is_int`, else `None`; and
  `disagreements` as `disagree` else `disagreements`.
- WHEN `dual` is an `int > 0` AND `disagreements` is an `int` with `0 <= disagreements <= dual` THEN
  it SHALL return `round(disagreements / dual, 3)` (a coherent count pair).
- OTHERWISE it SHALL return `round(float(disagreement_rate), 3)` when the stored `disagreement_rate`
  is `_is_number`, else `None` (an incoherent pair — `disagreements > dual` — falls through to the
  stored rate, never yielding a rate above `1.0`).
- `_disagreement_rate(source)` SHALL prefer `judge_order_stats` over `judge_report`, returning the
  first telemetry block that yields a non-`None` rate, else `None`.

### Evaluated partition (`_judge_source`)

- `_judge_source(result)` SHALL return the `tuned` partition when both `tuned` and `held_out` are
  dicts, otherwise `result` itself.

### Gate (`check_judge`)

- `source` SHALL be `_judge_source(result)`; `dual_order` SHALL be `source["judge_dual_order"]`;
  `dual_tasks` SHALL be `_dual_order_tasks(source)`; `disagreement` SHALL be
  `_disagreement_rate(source)`.
- The result SHALL always carry `passed`, `checks`, `dual_order`, `dual_order_tasks`,
  `disagreement_rate`, `max_disagreement`, `min_dual_order_tasks`; `dual_order_tasks` /
  `disagreement_rate` SHALL be their value when `_is_number` else `None`; `passed` SHALL be
  `all(c["passed"] for c in checks)`.
- Three checks SHALL be added in order: `dual_order_judging`, `enough_dual_order_tasks`,
  `low_disagreement`.
- `dual_order_judging` SHALL pass when the `judge_dual_order` flag is present and `is True`; WHEN the
  flag is `None` (a multi-repo aggregate omits it) THEN it SHALL pass when `_is_number(dual_tasks)
  and dual_tasks > 0`; no flag and no count SHALL fail closed. Detail SHALL be
  `"judged in both presentation orders"` on pass, else
  `"not dual-order judged (judge_dual_order={dual_order!r}, dual_order_tasks={dual_tasks!r})"`.
- `enough_dual_order_tasks` SHALL pass when `_is_number(dual_tasks) and dual_tasks >=
  min_dual_order_tasks`; detail SHALL be `"{dual_tasks} dual-order task(s) (min {min})"` when
  numeric, else `"dual-order task count unavailable"`.
- `low_disagreement` SHALL pass when `_is_number(disagreement) and disagreement <= max_disagreement`;
  detail SHALL be `"disagreement_rate {rate} <= {max}"` when numeric, else
  `"disagreement_rate unavailable/not numeric ({disagreement!r})"`.
- The result's `dual_order` key SHALL echo the effective `is_dual` status the gate acted on.

### Checks-row sanitation (`_check_rows_list`)

- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, is missing `name`/`passed`, has a
  non-`str` or empty `name`, or a `passed` that is not `_is_passed` (native/numpy bool).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy.
- WHEN no sanitized checks exist THEN `judge_headline` SHALL be exactly `judge: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `judge: ROBUST (dual-order, {dual_order_tasks} tasks, disagreement {disagreement_rate})`.
- OTHERWISE it SHALL be `judge: SHAKY ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_judge()` SHALL NOT mutate its input, and a non-dict `result` SHALL fail the checks rather
  than raise.

## Out of scope

- The disagreement telemetry's own reporting (`disagreement_outlook`) and the promotion decision
  (`promotion`).
- Tuning the default thresholds.

## Verification

- `tests/test_spec_071_judge_gate.py` exercises each EARS block above, pinning **literal** expected
  check names, `passed` values and detail strings, using values whose `repr` is stable across
  platforms.
- Broader coverage (including the CLI) remains in `tests/test_judge_gate.py`.
