# Spec 033 — decisive rate summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #949
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/win_rate.py`](../../benchmark/win_rate.py) (challenger/baseline/tie rates),
  [`benchmark/judge_wlt.py`](../../benchmark/judge_wlt.py) (compact judge_report block)

This spec makes the **existing, implicit** decisive-rate contract explicit. It describes the
as-built behavior of `benchmark/decisive_rate.py`; it introduces **no behavior change**.
Replay tallies must be summarized deterministically so CI dashboards can spot memorized-tie
artifacts — that read-only contract must be written down and verified.

## Why

`win_rate` reports challenger/baseline/tie rates separately; `summarize_decisive_rate()` focuses
on how often judging produced a decisive winner (challenger or baseline) versus a tie. The input
guards, zero-total semantics, and headline formatting must be explicit so contract changes are
reviewable.

## User stories

1. **As a benchmark operator**, I can read decisive versus tie shares from a replay artifact
   tally without re-parsing raw counts.
2. **As a CI maintainer**, I can log a stable `decisive_rate_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling, zero-total versus all-tie semantics, and every
   headline branch are written down.

## Constants

- `DEFAULT_*` — **N/A.** This module defines no tunable defaults; missing or invalid inputs yield
  `None` fields rather than substituted constants.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `result` is not a `dict` THEN `summarize_decisive_rate(result)` SHALL treat it
  as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Tally parsing (`_tally_counts`)

- WHEN `result["tally"]` is not a `dict` THEN `_tally_counts` SHALL return `None`.
- WHEN any of `challenger`, `baseline`, or `tie` is missing, not a whole non-negative `int`, or
  is a `bool` THEN `_tally_counts` SHALL return `None`.
- WHEN all three counts are whole non-negative `int`s THEN `_tally_counts` SHALL return the
  `(challenger, baseline, tie)` tuple.

### Summarize decisive rate (`summarize_decisive_rate`)

- WHEN `_tally_counts` returns `None` THEN the summary SHALL set `total`, `decisive`, `tie`,
  `decisive_rate`, and `tie_share` to `None`.
- WHEN the tally total is `0` THEN `total`, `decisive`, and `tie` SHALL be `0`, and both
  `decisive_rate` and `tie_share` SHALL be `None` (distinct from a real `0.0` rate when every
  task is a tie).
- WHEN the tally total is greater than `0` THEN:
  - `decisive` SHALL equal `challenger + baseline`.
  - `decisive_rate` SHALL be `round(decisive / total, 3)`.
  - `tie_share` SHALL be `round(tie / total, 3)`.
- WHEN every task is a tie (`decisive == 0` and `total > 0`) THEN `decisive_rate` SHALL be
  `0.0` (not `None`).

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline rate
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Decisive rate headline

- `decisive_rate_headline(summary)` SHALL return a one-line human summary.
- WHEN `total` is not a whole `int` or is `<= 0` THEN the headline SHALL read
  `decisive rate: no tally available` — regardless of other fields.
- WHEN usable totals exist THEN the headline SHALL include `decisive/total`, formatted
  `decisive_rate`, tie count, and formatted `tie_share`.
- WHEN `decisive_rate` or `tie_share` is non-finite or non-numeric THEN the formatted rate
  SHALL display as `n/a` rather than raising.

### Logging

- **N/A.** The module imports a logger but emits no log records in the as-built implementation;
  contract tests document this absence rather than asserting `caplog` output.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_decisive_rate()` SHALL NOT mutate its input dict.

## Out of scope

- Win-rate breakdown by challenger/baseline (`benchmark/win_rate.py`).
- Judge W-L-T from `judge_report` (`benchmark/judge_wlt.py`).
- Changing replay tally emission semantics.

## Verification

- `tests/test_spec_033_decisive_rate.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_decisive_rate.py`.
