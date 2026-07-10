# Spec 026 — pairwise judge disagreement outlook

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #874
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/disagreement_outlook.py`](../../benchmark/disagreement_outlook.py) (this module),
  [`scripts/disagreement_outlook.py`](../../scripts/disagreement_outlook.py) (CLI),
  [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (`check_judge`, the pass/fail gate),
  [`specs/016-benchmark-regression/spec.md`](../016-benchmark-regression/spec.md)

This spec makes the **existing, implicit** disagreement-outlook contract explicit. It describes the
as-built behavior of `benchmark/disagreement_outlook.py` (`summarize_disagreement_outlook`,
`disagreement_outlook_headline`); it introduces **no behavior change**.

## Why

The pairwise judge scores each task in both presentation orders; when the two orders disagree, the
result is position-sensitive and less trustworthy. `check_judge` **pass/fails** judge robustness for
CI gating. This read-only utility instead **exposes** the `disagreement_rate` and `dual_order_tasks`
telemetry for a dashboard, with a simple `stable`/`unstable` verdict against a threshold — a report,
not a gate.

To avoid a **stale** `judge_report.disagreement_rate` misreporting a slice, the rate is derived from
the authoritative `judge_order_stats` counts (`disagree` / `dual_order_tasks`, or `agree + disagree
+ tie`) when present, falling back to `judge_report` only when stats are absent — mirroring
`check_judge`, `check_regression`, and `check_promotion`. The module is **pure analysis**: no I/O,
never mutates its input, and missing or non-finite telemetry yields `None` fields rather than raising.

## User stories

1. **As a CI dashboard**, I can read a run's disagreement rate, dual-order task count, and a
   `stable`/`unstable` verdict without re-running the gate.
2. **As a benchmark operator**, a generalization run reports per-partition (`tuned` / `held_out`)
   detail plus an overall outlook summed across both partitions.
3. **As a reviewer**, the source-preference order, the count-derivation rules, the verdict boundary,
   the threshold coercion, and the empty/degenerate-telemetry behavior are written down.

## Acceptance criteria (EARS)

### Input coercion & number validity

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_int(value)` SHALL return `True` only for a non-`bool` `int`.
- `_is_number(value)` SHALL return `True` only for a **finite**, non-`bool` `int`/`float`; `NaN`,
  `±Inf`, `bool`, and non-numeric types SHALL return `False`, and an oversized `int`
  (`OverflowError`) SHALL return `False` rather than raise.

### Disagreement counts (`_disagreement_counts`)

Returns `(disagreements, dual_order_tasks)` only when both are valid **non-negative** ints; otherwise
`None`.

- `dual_order_tasks` SHALL be taken directly when it is an int; otherwise it SHALL be derived as
  `agree + disagree + tie` when all three are non-negative ints, else the block is unusable (`None`).
- `disagreements` SHALL be `disagree`, falling back to `disagreements`, falling back to
  `round(disagreement_rate * dual)` when a numeric rate and an int `dual` are available; if none of
  these yields a value the block is unusable (`None`).
- WHEN either resolved value is not a non-negative int THEN the result SHALL be `None`.

### Slice summary (`_slice_summary`)

- A slice SHALL be summarized by preferring `judge_order_stats` over `judge_report`: the **first**
  source that yields both a `(disagreements, dual)` count **and** a derivable rate wins.
- WHEN neither source yields a usable count-and-rate THEN the slice SHALL be the empty slice
  `{dual_order_tasks: None, disagreements: None, disagreement_rate: None}`.
- A non-dict slice or non-dict source SHALL be coerced to `{}` and contribute nothing.

### Overall summary (`summarize_disagreement_outlook`)

Every result SHALL include exactly the keys: `kind`, `dual_order_tasks`, `disagreements`,
`disagreement_rate`, `verdict`, `stable_threshold`, `partitions`.

- `kind` SHALL be `artifact_kind(artifact)` — `single`, `multi`, `generalization`, or `invalid`
  (a non-dict or empty artifact is `invalid`).
- For a `single`/`multi`/`invalid` artifact, the top-level slice summary SHALL populate
  `dual_order_tasks` / `disagreements` / `disagreement_rate`, and `partitions` SHALL be `None`.
- For a `generalization` artifact (both `tuned` and `held_out` dicts and a `generalization_gap`
  key), `partitions` SHALL carry the `tuned` and `held_out` slice summaries, and the top-level
  telemetry SHALL be the **combined** outlook.
- `verdict` SHALL be `stable` when `disagreement_rate <= stable_threshold`, `unstable` when it
  exceeds the threshold, and `None` when the rate is not a finite number.
- `stable_threshold` SHALL be `float(stable_threshold)` when it is a finite number, otherwise the
  `DEFAULT_STABLE_THRESHOLD` of `0.3`; the coerced value SHALL be echoed in the result.
- The function SHALL NOT raise for any input; a missing, non-finite, negative, or non-int telemetry
  value SHALL yield `None` fields, never an exception.

### Combined outlook across partitions (`_combined`)

- The combined outlook SHALL be computed **only when both** partition summaries carry int
  `dual_order_tasks` **and** int `disagreements`; otherwise it SHALL be the empty slice (all `None`).
- WHEN both are complete THEN `dual_order_tasks` = the sum, `disagreements` = the sum, and
  `disagreement_rate` = `round(sum_disagreements / sum_dual, 3)`.
- WHEN both are complete but the summed `dual_order_tasks` is `0` THEN `dual_order_tasks` = `0`,
  `disagreements` = `0`, and `disagreement_rate` = `None` (no division by zero).
- Because a partition with `dual_order_tasks == 0` cannot yield a derivable rate, its slice summary
  is the empty slice; therefore an **artifact** whose partitions both have zero dual-order tasks
  yields an all-`None` overall outlook via `_slice_summary`, not the `_combined` zero branch.

### Verdict (`_verdict`)

- WHEN `rate` is not a finite number THEN `_verdict` SHALL return `None`.
- OTHERWISE it SHALL return `stable` when `rate <= threshold`, else `unstable`. The boundary is
  inclusive: a rate **equal** to the threshold is `stable`.

### Disagreement outlook headline (`disagreement_outlook_headline`)

- The rate SHALL be rendered as a percentage (`{:.1%}`) when numeric, else `n/a`; the verdict SHALL
  be its value or `unknown` when absent; `dual_order_tasks` SHALL be its value or `n/a` when not an
  int.
- For a `single`/`multi` summary the line SHALL be
  `disagreement outlook: {verdict} (rate {rate}, {dual} dual-order task(s))`.
- For a `generalization` summary the line SHALL additionally append
  `[tuned {tuned_rate}, held-out {held_rate}]` with each partition rate rendered the same way.
- A non-dict summary SHALL be coerced to `{}` and render the all-`unknown`/`n/a` line, never raise.

### Pure evaluation

- The module SHALL perform **no I/O** — a call to `summarize_disagreement_outlook` or
  `disagreement_outlook_headline` SHALL touch neither the filesystem nor the network.
- `summarize_disagreement_outlook()` SHALL **NOT mutate** its `artifact` argument, for well-formed
  **and** every degenerate shape (non-dict, empty, single, multi, generalization, missing / negative
  / non-int / non-finite telemetry). The contract is verified by deep-copying each input before the
  call and asserting the input is unchanged afterward (a value-equality check).

## Verification

- `tests/test_spec_026_disagreement_outlook.py` exercises each EARS block above, including the
  source-preference (stats over stale report), the count-derivation branches, the generalization
  combined outlook and its zero-dual edge, the verdict boundary, threshold coercion, the headline
  branches, and the deep non-mutation / no-I/O purity checks.
- Broader coverage (including the CLI) remains in `tests/test_disagreement_outlook.py`.
