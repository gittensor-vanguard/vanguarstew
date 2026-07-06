# Spec 037 — tie order share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #987
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/order_agree_rate.py`](../../benchmark/order_agree_rate.py) (dual-order agree rate),
  [`benchmark/decisive_rate.py`](../../benchmark/decisive_rate.py) (tally-based tie share)

This spec makes the **existing, implicit** tie-order-share contract explicit. It describes the
as-built behavior of `benchmark/tie_order_share.py`; it introduces **no behavior change**. Replay
artifacts carry `judge_order_stats.tie` counts from dual-order judging — that stability signal
must be written down and verified.

## Why

`order_agree_rate` reports agree rate among dual-order tasks only; `decisive_rate` derives tie
share from replay tally, not judge order stats. `summarize_tie_order_share()` is the reproducible
read-only summary for CI dashboards; making its contract explicit lets reviewers check
tie-order-share changes against intent.

## User stories

1. **As a benchmark operator**, I can read `tie / total` categorized tasks before trusting a
   replay headline when judge stability matters.
2. **As a CI maintainer**, I can log a stable `tie_order_share_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_tie_order_share(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer (avoids truthy counts).
- `float` values — including whole-number floats such as `5.0` — SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline share
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Judge order stats keys

- `_slice_summary` SHALL read `agree`, `disagree`, `tie`, `single`, and `offline` from
  `judge_order_stats` when that value is a `dict`.
- WHEN `judge_order_stats` is missing or not a `dict` THEN all five counts SHALL be treated as
  missing (`None` from `.get()`).

### Slice summary (`_slice_summary`)

- WHEN every count is a non-negative `_is_int` THEN `total` SHALL be the sum of all five counts
  and `tie` SHALL be the `tie` count.
- WHEN any count is missing, not an `_is_int`, or negative THEN the slice SHALL return
  `{"total": None, "tie": None, "tie_order_share": None}`.
- WHEN all counts are valid and `total > 0` THEN `tie_order_share` SHALL be
  `round(tie / total, 3)` (a finite value in `[0.0, 1.0]`).
- WHEN all counts are valid and `total == 0` THEN `total` SHALL be `0`, `tie` SHALL echo the tie
  count (typically `0`), and `tie_order_share` SHALL be `None` (distinct from `0.0`).

### Artifact-kind branches (`summarize_tie_order_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL always include these keys (never omitted):

| Key | Always present | Value when unavailable |
| --- | --- | --- |
| `kind` | yes | `artifact_kind` result (`"invalid"` for empty/non-classifiable input) |
| `total` | yes | `None` when stats incoherent or missing |
| `tie` | yes | `None` when stats incoherent or missing |
| `tie_order_share` | yes | `None` when share cannot be computed |
| `partitions` | yes | `None` for non-generalization kinds; dict for `generalization` |

1. **`single` or `multi`** — top-level fields come from `_slice_summary(artifact)`;
   `partitions` SHALL be `None`.
2. **`generalization`** — SHALL report per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]` (each via `_slice_summary` on that partition), plus overall counts
   from summing both partitions' `total` and `tie` WHEN both partitions carry coherent `_is_int`
   values for those fields; otherwise overall `total`, `tie`, and `tie_order_share` SHALL all be
   `None`.
3. **`invalid`** — SHALL return `kind == "invalid"` with `total`, `tie`, and `tie_order_share`
   all `None`, and `partitions` `None`.

### Tie order share headline

`tie_order_share_headline(summary)` SHALL return a one-line human summary.

- WHEN the input is not a `dict` THEN it SHALL be coerced via `_dict` (same as missing keys).
- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `tie-order share: no judge stats available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `tie-order share: {share_txt} ({tie_txt}/{total} categorized task(s))` where:
  - `share_txt` is `f"{share:.1%}"` when `tie_order_share` passes `_is_number`, otherwise `n/a`;
  - `tie_txt` is `str(tie)` when `tie` passes `_is_int`, otherwise `n/a`.

Exact examples (character-for-character):

| Condition | Expected headline |
| --- | --- |
| `tie_order_share=0.5`, `tie=2`, `total=4` | `tie-order share: 50.0% (2/4 categorized task(s))` |
| `tie_order_share=0.0`, `tie=0`, `total=4` | `tie-order share: 0.0% (0/4 categorized task(s))` |
| `total=0` | `tie-order share: no judge stats available` |
| `total=None` | `tie-order share: no judge stats available` |
| `tie_order_share=None`, `total=3`, `tie=1` | `tie-order share: n/a (1/3 categorized task(s))` |
| `tie_order_share=float("nan")`, `total=3`, `tie=1` | `tie-order share: n/a (1/3 categorized task(s))` |

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_tie_order_share()` SHALL NOT mutate its input dict.

## Out of scope

- Pairwise judge execution and `judge_order_stats` production — `benchmark/judge.py`.
- Tally-based tie share — `benchmark/decisive_rate.py`.
- Changing extraction semantics — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_037_tie_order_share.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_tie_order_share.py`.
