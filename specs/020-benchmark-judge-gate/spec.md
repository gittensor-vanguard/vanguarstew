# Spec 020 — the pairwise-judge robustness gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #820
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/004-pairwise-judge`](../004-pairwise-judge/spec.md) (ranking under test),
  [`specs/017-benchmark-judge-calibration`](../017-benchmark-judge-calibration/spec.md) (offline corpus)

This spec makes the **existing, implicit** judge-gate contract explicit. It describes the
as-built behavior of `benchmark/judge_gate.py`; it introduces **no behavior change**. Replay
composite scores depend on pairwise judging — so dual-order coverage, disagreement thresholds,
and gate headlines must be written down and verified.

## Why

A run judged in a single presentation order, or with high order disagreement, yields a shaky
win/loss record. `check_judge()` turns that into reproducible pass/fail criteria. Making the
contract explicit lets reviewers check judge-gate changes against intent.

## User stories

1. **As a benchmark operator**, I can verify a saved replay artifact cleared the judge-robustness
   bar before trusting its composite — so shaky verdicts fail closed in CI.
2. **As a maintainer**, I know how dual-order task counts are resolved from `judge_report` vs
   `judge_order_stats` — so gate behavior stays predictable.
3. **As a reviewer**, disagreement-rate handling (including legitimate `0.0` vs unavailable) and
   malformed-result robustness are written down — so changes are checked against the spec.

## Acceptance criteria (EARS)

### Judge robustness checks

- `check_judge(result, max_disagreement=..., min_dual_order_tasks=...)` SHALL evaluate three
  named checks and return `{"passed", "checks", "dual_order", "dual_order_tasks",
  "disagreement_rate", ...thresholds}`.
- `passed` SHALL be `True` only when every check passes.
- The checks SHALL always include:
  1. `dual_order_judging` — `judge_dual_order` is exactly `True`;
  2. `enough_dual_order_tasks` — dual-order task count is numeric and
     `>= min_dual_order_tasks`;
  3. `low_disagreement` — `disagreement_rate` is numeric and `<= max_disagreement`.
- WHEN `result` is not a dict THEN every check SHALL fail closed without raising.
- The function SHALL NOT mutate the input `result`.

### Dual-order task count resolution

- `_dual_order_tasks(result)` SHALL read `dual_order_tasks` from `judge_report` first, then
  fall back to `judge_order_stats`.
- WHEN neither source provides a numeric count THEN the count SHALL be treated as unavailable
  (`None`) and `enough_dual_order_tasks` SHALL fail.

### Disagreement rate handling

- `disagreement_rate` SHALL be read from `judge_report`.
- WHEN `disagreement_rate` is a finite numeric value (including **0.0**) and
  `<= max_disagreement` THEN `low_disagreement` SHALL pass — zero disagreement is a legitimate
  measurement, not a missing placeholder.
- WHEN `disagreement_rate` is missing or non-numeric THEN `low_disagreement` SHALL fail and the
  exported `disagreement_rate` field SHALL be `None` (unavailable, distinct from `0.0`).
- WHEN `disagreement_rate` is NaN or cannot satisfy `<= max_disagreement` THEN `low_disagreement`
  SHALL fail (non-finite or out-of-range rates are not trusted).
- The bound SHALL be inclusive: `disagreement_rate == max_disagreement` passes.

### Threshold configuration

- `max_disagreement` and `min_dual_order_tasks` SHALL be forwarded into the returned result for
  traceability.
- Callers SHALL be able to tighten or loosen thresholds per run.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN a check row is not a dict or is missing `name`/`passed` THEN that row SHALL be skipped
  with a warning.
- `failed_checks(result)` SHALL return failed check names from usable rows only.

### Judge headline

- `judge_headline(result)` SHALL return a one-line human summary.
- IF usable `checks` is empty THEN the headline SHALL read `judge: no checks evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `ROBUST`.
- WHEN `result["passed"]` is false THEN the headline SHALL include `SHAKY` and failed check names.
- Malformed `checks` fields SHALL NOT crash headline formatting.

### Pure evaluation

- The module SHALL perform no I/O.
- Evaluation SHALL never mutate the input replay result dict.

## Out of scope

- Pairwise ranking rules (`benchmark/judge.py`) — spec 004.
- Judge calibration corpus (`benchmark/judge_calibration.py`) — spec 017.
- Changing default thresholds — documented as constants only.

## Verification

- `tests/test_spec_020_judge_gate.py` (this PR) exercises each EARS block above.
- Broader coverage remains in `tests/test_judge_gate.py`.
