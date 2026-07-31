# Spec 042 — tie-order share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1100
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/dual_order_share.py`](../../benchmark/dual_order_share.py) (dual-presentation counterpart)

This spec makes the **existing, implicit** tie-order-share contract explicit. It describes the
as-built behavior of `benchmark/tie_order_share.py` (merged #955); it introduces **no behavior
change**. A judge that ties a large share of its categorized outcomes is a weaker discriminator
than the headline suggests — that tie share must be written down and verified.

## Why

`benchmark/judge.py` records per-outcome `judge_order_stats` (`agree`/`disagree`/`tie` categorize
a dual-presentation verdict; `single`/`offline` are the non-dual outcomes). Nothing summarized how
large a share of the *categorized* outcomes ended in a tie. `summarize_tie_order_share()` is the
reproducible read-only summary for CI dashboards; making its contract explicit lets reviewers check
tie-order-share changes against intent.

## User stories

1. **As a benchmark operator**, I can read `tie / total` before trusting how decisively a run's
   judge separated the candidates.
2. **As a CI maintainer**, I can log a stable `tie_order_share_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling, the generalization partition split, and every
   headline branch are written down.

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

### Order-stats extraction (`_order_stats`)

- `_order_stats(slice_)` SHALL return the slice's `judge_order_stats` mapping when it is a `dict`.
- WHEN the slice is not a `dict`, or `judge_order_stats` is missing or not a `dict`, THEN
  `_order_stats` SHALL return `{}`.

### Slice summary (`_slice_summary`)

- The categorized outcome keys SHALL be `agree`, `disagree`, `tie`, `single`, `offline`; the tie
  count SHALL be the `tie` field.
- WHEN every one of the five keys is present, an `int` (not `bool`), and `>= 0` THEN `total` SHALL
  be their sum and `tie` SHALL be the `tie` count.
- WHEN any of the five counts is missing, non-`int`, `bool`, or negative THEN the slice SHALL
  return `{"total": None, "tie": None, "tie_order_share": None}`.
- WHEN the counts are coherent AND `total == 0` THEN the slice SHALL return
  `{"total": 0, "tie": 0, "tie_order_share": None}` (no share is defined over zero categorized
  outcomes, but the zero counts are reported).
- WHEN the counts are coherent AND `total > 0` THEN `tie_order_share` SHALL be
  `round(tie / total, 3)`.

### Artifact-kind branches (`summarize_tie_order_share`)

- Every returned summary SHALL include the keys `kind`, `total`, `tie`, `tie_order_share`, and
  `partitions`.
- WHEN `kind` is `single`, `multi`, or `invalid` THEN the summary SHALL carry the top-level slice
  summary and `partitions` SHALL be `None`.
- WHEN `kind` is `generalization` THEN the summary SHALL carry a `partitions` mapping with a
  `tuned` and a `held_out` slice summary, plus an overall `total`/`tie`/`tie_order_share`.
- WHEN `kind` is `generalization` AND both partitions report an `int` `total` and an `int` `tie`
  THEN the overall `total`/`tie` SHALL be their sums and the overall `tie_order_share` SHALL be
  `round(tie / total, 3)` when `total > 0`, else `None`.
- WHEN `kind` is `generalization` AND either partition's `total` or `tie` is not an `int` (a
  malformed partition) THEN the overall `total`/`tie`/`tie_order_share` SHALL all be `None`, while
  each partition's own summary is still reported.

### Tie-order share headline (`tie_order_share_headline`)

- WHEN the summary is not a `dict`, or `total` is not an `int`, or `total == 0` THEN the headline
  SHALL be exactly `"tie-order share: no judge stats available"`.
- WHEN `total` is a positive `int` THEN the headline SHALL be
  `"tie-order share: {share:.1%} ({tie}/{total} categorized task(s))"`, where `share` is the
  `tie_order_share` formatted as a percentage when numeric else `"n/a"`, and `tie` is the tie count
  when it is an `int` else `"n/a"`.

### Pure evaluation

- `summarize_tie_order_share` SHALL NOT mutate its input artifact.
- The module SHALL perform no I/O and SHALL never raise on malformed input (malformed counts yield
  `None` share fields instead).
