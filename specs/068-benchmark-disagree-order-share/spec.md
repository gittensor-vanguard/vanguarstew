# Spec 068 — disagree order share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1919
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/order_share.py`](../../benchmark/order_share.py) (the shared
  `make_order_share` factory this binds), [`benchmark/agree_order_share.py`](../../benchmark/agree_order_share.py)
  (sibling binding, Spec 038), [`benchmark/comparability.py`](../../benchmark/comparability.py)
  (artifact kind classification)

This spec makes the **existing, implicit** disagree-order-share contract explicit. It describes the
as-built behavior of `benchmark/disagree_order_share.py`; it introduces **no behavior change**.

## Why

`agree`/`single`/`dual`/`tie`/`offline`/`skip` order-share bindings each have a spec (038–043);
`disagree_order_share` is the one remaining order-share binding without one. It is a thin binding
over the shared `benchmark.order_share.make_order_share` factory with `numerator_keys=("disagree",)`,
reporting `disagree` as a fraction of all categorized judge outcomes. Making its contract explicit
lets reviewers check disagree-order-share changes against intent, and pins that it behaves
**identically** to its documented siblings (same factory, same helpers — no divergence).

## User stories

1. **As a benchmark operator**, I can read `disagree / total` categorized tasks for
   judge-stability dashboards.
2. **As a CI maintainer**, I can log a stable `disagree_order_share_headline()` string alongside
   the JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Binding

- `benchmark/disagree_order_share.py` SHALL be a thin binding produced by
  `benchmark.order_share.make_order_share(numerator_keys=("disagree",), count_field="disagree",
  share_field="disagree_order_share", headline_label="disagree-order share")`.
- It SHALL export `summarize_disagree_order_share`, `disagree_order_share_headline`,
  `_slice_summary`, and re-export `_dict`, `_is_int`, `_is_number`, `_order_stats` from
  `benchmark.order_share`.
- `STAT_KEYS` SHALL be `("agree", "disagree", "tie", "single", "offline")`.

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_disagree_order_share(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_order_stats(slice_)` SHALL return the slice's `judge_order_stats` when it is a `dict`, else `{}`
  (coercing a non-dict slice via `_dict` first).

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values (including whole-valued floats like `3.0`) SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline share
  formatting.
- `bool`, `NaN`, `inf`, `-inf`, and non-numeric types SHALL NOT be treated as numeric.

### Slice summary (`_slice_summary`)

- `_slice_summary` SHALL read all five `judge_order_stats` counts in `STAT_KEYS`: `agree`,
  `disagree`, `tie`, `single`, `offline`.
- WHEN any count is not a non-negative `_is_int` THEN the slice SHALL return
  `{"total": None, "disagree": None, "disagree_order_share": None}`.
- WHEN all counts are valid and `total > 0` THEN `total` SHALL be their sum, `disagree` SHALL be
  the disagree count, and `disagree_order_share` SHALL be `round(disagree / total, 3)`.
- WHEN all counts are valid and `total == 0` THEN `total` SHALL be `0`, `disagree` SHALL echo the
  disagree count (`0`), and `disagree_order_share` SHALL be `None`.

### Artifact-kind branches (`summarize_disagree_order_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`. Every summary SHALL
include the keys: `kind`, `total`, `disagree`, `disagree_order_share`, `partitions`.

1. **`single` or `multi`** — top-level fields from `_slice_summary(artifact)`; `partitions` SHALL
   be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`. The overall `total`/`disagree`/`disagree_order_share` SHALL be summed
   from both partitions **only when each partition's `disagree_order_share` is not `None`** (i.e.
   each partition is coherent with `total > 0`); OTHERWISE the overall fields SHALL each be `None`.
   A zero-task partition (integer counts, `None` share) SHALL therefore withhold the overall,
   rather than masking incoherence behind the other partition alone.
3. **`invalid`** — `total`, `disagree`, `disagree_order_share` and `partitions` SHALL all be `None`.

### Disagree order share headline

- WHEN `total` is missing, not an `_is_int`, or `0` THEN the headline SHALL be exactly:
  `disagree-order share: no judge stats available`.
- WHEN `total` is a positive `_is_int` THEN the headline SHALL be
  `disagree-order share: {share_txt} ({num_txt}/{total} categorized task(s))`, where `share_txt`
  is `f"{share:.1%}"` when `disagree_order_share` passes `_is_number` else `n/a`, and `num_txt`
  is `str(disagree)` when `disagree` passes `_is_int` else `n/a`.
- A non-dict `summary` SHALL be coerced to `{}` and yield the `no judge stats available` headline.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_disagree_order_share()` SHALL NOT mutate its input dict.

## Out of scope

- The shared `make_order_share` factory internals (documented via the sibling order-share specs).
- The disagreement *outlook* metric (`benchmark/disagreement_outlook.py`, Spec 026), a distinct
  module.

## Verification

- `tests/test_spec_068_disagree_order_share.py` exercises each EARS block above, including
  `_is_int`/`_is_number` semantics, the slice happy/zero-total/malformed/negative branches, all
  three artifact-kind branches (with a partial and a malformed generalization partition), and
  every headline branch (`no stats`, exact format, `None` share → `n/a`, `NaN` share → `n/a`,
  non-dict summary).
- Broader coverage (including the CLI) remains in `tests/test_disagree_order_share.py`.
