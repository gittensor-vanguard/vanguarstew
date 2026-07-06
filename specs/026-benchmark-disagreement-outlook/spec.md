# Spec 026 — disagreement outlook (`summarize_disagreement_outlook`, `disagreement_outlook_headline`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #874
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (pass/fail gate),
  [`benchmark/judge.py`](../../benchmark/judge.py) (telemetry producer)

This spec makes the **existing, implicit** disagreement-outlook contract explicit. It describes
the as-built behavior of `benchmark/disagreement_outlook.py`; it introduces **no behavior change**.
Pairwise judge runs emit `disagreement_rate` and `dual_order_tasks` telemetry; this utility
exposes a stable/unstable verdict for CI dashboards.

## Why

`judge_gate` pass/fails judge robustness; operators also need a read-only outlook with a simple
verdict. Making the telemetry extraction and threshold rules explicit lets reviewers verify
dashboard changes against intent.

## User stories

1. **As a benchmark maintainer**, I know which artifact fields feed disagreement telemetry — so
   saved artifacts with only `judge_order_stats` still produce a summary.
2. **As a reviewer**, non-finite rate handling and threshold defaults are written down — so
   outlook changes are checked against the spec.

## Constants

- `DEFAULT_STABLE_THRESHOLD` — `0.3`; used when `stable_threshold` is missing or non-finite.

## Acceptance criteria (EARS)

### Input guard

- `summarize_disagreement_outlook(artifact, stable_threshold=DEFAULT_STABLE_THRESHOLD)` SHALL
  accept any value for `artifact`.
- WHEN `artifact` is not a `dict` THEN the function SHALL treat it as `{}` (not raise) and
  `kind` SHALL be `"invalid"`.

### Telemetry source

- The function SHALL read telemetry from `artifact["judge_report"]` when that value is a `dict`.
- WHEN `judge_report` is not a `dict` THEN the function SHALL fall back to
  `artifact["judge_order_stats"]` when that value is a `dict`.
- WHEN neither source is a `dict` THEN `dual_order_tasks`, `disagreement_rate`, and `verdict`
  SHALL be `None`.

### `dual_order_tasks`

- WHEN the telemetry dict carries `dual_order_tasks` as a non-negative `int` (not a `bool`) THEN
  the summary SHALL include that value.
- WHEN `dual_order_tasks` is missing, negative, a `bool`, a float, or non-integer THEN the summary
  SHALL set `dual_order_tasks` to `None`.

### `disagreement_rate`

- WHEN the telemetry dict carries a finite numeric `disagreement_rate` THEN the summary SHALL
  include it rounded to three decimal places.
- WHEN `disagreement_rate` is missing, non-numeric, `NaN`, infinite, or a `bool` THEN the summary
  SHALL set `disagreement_rate` to `None`.

### Verdict

- WHEN `disagreement_rate` is a finite number and `disagreement_rate <= stable_threshold` THEN
  `verdict` SHALL be `"stable"`.
- WHEN `disagreement_rate` is a finite number and `disagreement_rate > stable_threshold` THEN
  `verdict` SHALL be `"unstable"`.
- WHEN `disagreement_rate` is unavailable THEN `verdict` SHALL be `None`.
- WHEN `disagreement_rate` equals `stable_threshold` exactly THEN `verdict` SHALL be `"stable"`.

### Threshold parameter

- `stable_threshold` SHALL default to `DEFAULT_STABLE_THRESHOLD`.
- WHEN `stable_threshold` is not a finite number THEN the function SHALL use
  `DEFAULT_STABLE_THRESHOLD`.
- The returned `stable_threshold` field SHALL reflect the threshold actually used.

### Artifact kind

- `kind` SHALL be the result of `artifact_kind(artifact)`.

### Headline

- `disagreement_outlook_headline(summary)` SHALL accept any value; non-dict input SHALL be treated
  as `{}`.
- WHEN `disagreement_rate` is a finite number THEN the headline SHALL format it as a percentage
  with one decimal place.
- WHEN `disagreement_rate` is unavailable THEN the headline SHALL show `"n/a"` for the rate.
- WHEN `verdict` is unavailable THEN the headline SHALL show `"unknown"` for the verdict.
- WHEN `dual_order_tasks` is unavailable THEN the headline SHALL show `"n/a"` for the dual-order
  count.

### Pure evaluation

- Both functions SHALL perform no I/O and SHALL NOT mutate their inputs.

## Out of scope

- Judge gate pass/fail logic — `benchmark/judge_gate.py`.
- Pairwise judge execution — `benchmark/judge.py`.
- Changing threshold semantics — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_026_disagreement_outlook.py` (this PR) exercises each EARS block above.
- Broader coverage remains in `tests/test_disagreement_outlook.py`.
