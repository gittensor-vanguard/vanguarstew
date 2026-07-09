# Spec 025 — judge W-L-T summary (`summarize_judge_wlt`, `judge_wlt_headline`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #873
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/win_rate.py`](../../benchmark/win_rate.py) (tally-based rates),
  [`benchmark/judge.py`](../../benchmark/judge.py) (pairwise judge producer)

This spec makes the **existing, implicit** judge W-L-T summary contract explicit. It describes
the as-built behavior of `benchmark/judge_wlt.py`; it introduces **no behavior change**.
Replay artifacts may carry a compact `judge_report` block instead of a full `tally`; this utility
normalizes wins/losses/ties for CI dashboards.

## Why

`win_rate` reads challenger/baseline/tie counts from `tally`; many saved artifacts only retain the
summarized `judge_report` W-L-T block. Making the extraction contract explicit lets reviewers
verify dashboard and CLI changes against intent.

## User stories

1. **As a benchmark maintainer**, I know how W-L-T counts are read from `judge_report` — so saved
   artifacts without a `tally` still produce a stable summary.
2. **As a reviewer**, malformed-input guards and headline formatting are written down — so
   judge-summary changes are checked against the spec.

## Acceptance criteria (EARS)

### Input guard

- `summarize_judge_wlt(artifact)` SHALL accept any value.
- WHEN `artifact` is not a `dict` THEN the function SHALL treat it as `{}` (not raise).
- WHEN `artifact` is not a `dict` THEN `kind` SHALL be `"invalid"` and all count fields SHALL be
  `None`.

### W-L-T extraction

- The function SHALL read `wins`, `losses`, and `ties` from `artifact["judge_report"]` when that
  value is a `dict`.
- Each count SHALL be a non-negative `int` (booleans and floats SHALL be rejected).
- WHEN all three counts are valid THEN the function SHALL return them and set `total` to
  `wins + losses + ties`.
- WHEN `judge_report` is missing, not a `dict`, or any count is invalid THEN `wins`, `losses`,
  `ties`, and `total` SHALL all be `None`.

### Zero total

- WHEN all three counts are valid integers summing to `0` THEN `total` SHALL be `0` (not `None`).

### Artifact kind

- `kind` SHALL be the result of `artifact_kind(artifact)` from
  [`benchmark/comparability.py`](../../benchmark/comparability.py).

### Headline — unavailable

- `judge_wlt_headline(summary)` SHALL accept any value; non-dict input SHALL be treated as `{}`.
- WHEN `total` is missing, not a non-negative `int`, or `0` THEN the headline SHALL be
  `"judge wlt: unavailable"`.
- WHEN any of `wins`, `losses`, or `ties` is not a non-negative `int` THEN the headline SHALL be
  `"judge wlt: unavailable"`.

### Headline — happy path

- WHEN `wins`, `losses`, `ties`, and `total` are valid non-negative integers and `total > 0` THEN
  the headline SHALL be `"judge wlt: {wins}-{losses}-{ties} over {total} task(s)"`.

### Pure evaluation

- Both functions SHALL perform no I/O and SHALL NOT mutate their inputs.

## Out of scope

- Pairwise judge execution and `judge_report` production — `benchmark/judge.py`.
- Challenger/baseline/tie rates from `tally` — `benchmark/win_rate.py`.
- Changing extraction semantics — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_025_judge_wlt.py` (this PR) exercises each EARS block above.
- Broader coverage remains in `tests/test_judge_wlt.py`.
