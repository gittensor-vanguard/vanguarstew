# Spec 035 — win rate summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #972
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/judge_wlt.py`](../../benchmark/judge_wlt.py) (compact judge-report block),
  [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (whole-number count parsing)

This spec makes the **existing, implicit** win-rate contract explicit. It describes the
as-built behavior of `benchmark/win_rate.py`; it introduces **no behavior change**. A replay
headline `composite_mean` can look healthy while the underlying pairwise tally is thin or
lopsided — that tally signal must be written down and verified.

## Why

`run_replay` records a `tally` of challenger/baseline/tie outcomes, but nothing summarizes those
counts as rates for CI dashboards. `summarize_win_rate()` is the reproducible read-only summary;
making its contract explicit lets reviewers check win-rate changes against intent.

## User stories

1. **As a benchmark operator**, I can read challenger/baseline/tie rates before trusting a replay
   headline composite.
2. **As a CI maintainer**, I can log a stable `win_rate_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling, zero-total semantics, and every headline branch
   are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `result` is not a `dict` THEN `summarize_win_rate(result)` SHALL treat it as
  `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number tally counts.
- `bool` SHALL NOT be treated as an integer (avoids truthy counts).
- `float` values — including whole-number floats such as `5.0` — SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline rate
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Tally counts (`_tally_counts`)

- SHALL read `challenger`, `baseline`, and `tie` from `result["tally"]` when `tally` is a `dict`
  (missing keys treated as `None`).
- WHEN `tally` is absent or not a `dict` THEN `_tally_counts` SHALL return `None`.
- WHEN every count passes `_is_int` AND is `>= 0` THEN `_tally_counts` SHALL return
  `(challenger, baseline, tie)`.
- WHEN any count fails `_is_int` OR is negative THEN `_tally_counts` SHALL return `None`.

### Win rate summary (`summarize_win_rate`)

Every summary SHALL always include these keys (never omitted):

| Key | Always present | Value when tally unavailable |
| --- | --- | --- |
| `total` | yes | `None` when tally missing or malformed |
| `challenger` | yes | `None` when tally missing or malformed |
| `baseline` | yes | `None` when tally missing or malformed |
| `tie` | yes | `None` when tally missing or malformed |
| `challenger_rate` | yes | `None` when rate cannot be computed |
| `baseline_rate` | yes | `None` when rate cannot be computed |
| `tie_rate` | yes | `None` when rate cannot be computed |

- WHEN `_tally_counts` returns `None` THEN all fields SHALL be `None`.
- WHEN `_tally_counts` returns counts with `total == 0` (all three counts zero) THEN
  `total`, `challenger`, `baseline`, and `tie` SHALL be `0`, and all three rate fields SHALL be
  `None` (distinct from a missing tally where `total` is `None`).
- WHEN `total > 0` THEN each rate SHALL be `round(count / total, 3)` for its respective count,
  yielding finite values in `[0.0, 1.0]`.

### Win rate headline

`win_rate_headline(summary)` SHALL return a one-line human summary.

- WHEN the input is not a `dict` THEN it SHALL be coerced via `_dict` (same as missing keys).
- WHEN `total` fails `_is_int` OR `total == 0` THEN the headline SHALL be exactly:
  `win rate: no tally available` — note the space after the colon and the lowercase literal
  `no tally available`.
- OTHERWISE the headline SHALL be exactly:
  `win rate: challenger {challenger}/{total} ({challenger_rate_txt}), baseline {baseline}, tie {tie}`
  where `{challenger_rate_txt}` is `f"{challenger_rate:.1%}"` when `challenger_rate` passes
  `_is_number`, otherwise the literal string `n/a` (lowercase, no quotes).

Exact examples (character-for-character):

| Condition | Expected headline |
| --- | --- |
| `challenger=6`, `baseline=3`, `tie=1`, `total=10`, `challenger_rate=0.6` | `win rate: challenger 6/10 (60.0%), baseline 3, tie 1` |
| `challenger=2`, `baseline=1`, `tie=0`, `total=3`, `challenger_rate=0.667` | `win rate: challenger 2/3 (66.7%), baseline 1, tie 0` |
| `challenger=0`, `baseline=0`, `tie=0`, `total=0`, rates `None` | `win rate: no tally available` |
| `total=None` (missing or malformed tally) | `win rate: no tally available` |
| `challenger=1`, `total=2`, `challenger_rate=float("nan")` | `win rate: challenger 1/2 (n/a), baseline 1, tie 0` |

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_win_rate()` SHALL NOT mutate its input dict.

## Out of scope

- Judge-report compact block parsing (`benchmark/judge_wlt.py`).
- Dual-order judge order stats (`benchmark/order_agree_rate.py`).
- Changing `run_replay` tally accounting semantics.

## Verification

- `tests/test_spec_035_win_rate.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_win_rate.py`.
