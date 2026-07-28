# Spec 063 — judge report integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1865
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (judge robustness),
  [`benchmark/tally_integrity.py`](../../benchmark/tally_integrity.py) (per-repo tally sums, Spec 030),
  [`benchmark/objective_integrity.py`](../../benchmark/objective_integrity.py) (anchor inputs, Spec 061)

This spec makes the **existing, implicit** judge-report contract explicit. It describes the
as-built behavior of `benchmark/judge_report_integrity.py`; it introduces **no behavior change**.

## Why

`run_replay` rolls pairwise outcomes into `judge_report` (W-L-T, disagreement telemetry) sourced
from `tally` and `judge_order_stats`. `judge_gate` checks whether the judge was robust enough to
trust, but nothing verifies the summary fields actually agree with the raw tallies and
order-sensitivity counters. A hand-edited artifact could report a low `disagreement_rate` while
the underlying stats say otherwise.

This is the **last** undocumented `benchmark/*integrity*.py` module (gap 027, aggregate 028, row
029, tally 030, task 057, score 059, objective 061 all have specs; weight 062 in flight).

## User stories

1. **As a benchmark operator**, I can trust that a CONSISTENT verdict means the judge summary
   agrees with its raw tallies and order-sensitivity stats.
2. **As a CI maintainer**, I can gate on `scripts/judge_report_integrity.py` and log a stable
   `integrity_headline()` string.
3. **As a reviewer**, every malformed-input, empty-slice, early-return, warning and headline
   branch is written down (addressing the incompleteness class of rejection seen on Specs
   057/059/061/062).

## Constants

- `_TALLY_KEYS` SHALL be `("challenger", "baseline", "tie")`.
- `_REPORT_TALLY` SHALL be `("wins", "losses", "ties")`, mapped positionally onto `_TALLY_KEYS`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.
- `_NUMPY_BOOL_TYPENAMES` SHALL be `{"bool_", "bool8", "bool"}` (`bool` for numpy 2.x).
- `check_judge_report_integrity` takes no tolerance; its result SHALL carry only `passed` and
  `checks`.

## Acceptance criteria (EARS)

### Numeric helper (`_is_number`)

- `_is_number(value)` SHALL be true only when `isinstance(value, (int, float))`, `value` is **not**
  a `bool`, and `math.isfinite(value)` is true.
- WHEN `value` is a `bool` THEN it SHALL be false.
- WHEN `value` is `NaN` / `inf` / `-inf` THEN it SHALL be false.
- WHEN `value` is an oversized `int` (`math.isfinite` raising `OverflowError`) THEN it SHALL be
  false rather than raising.
- WHEN `value` is a `str`, `None`, list, dict, or **any non-`int`/`float` numeric type such as
  `decimal.Decimal` or `fractions.Fraction`** THEN it SHALL be false (the helper is
  `isinstance`-based on the built-in `int`/`float` only).

### Verdict helper (`_is_passed`) — accepts bool, not int

- WHEN `type(value) is bool` THEN `_is_passed(value)` SHALL be true; an arbitrary `bool`
  **subclass** SHALL NOT be accepted (the check is `type(...) is bool`, not `isinstance`).
- WHEN `type(value).__name__` is in `_NUMPY_BOOL_TYPENAMES` THEN it SHALL be true (numpy scalar
  bool, no numpy import required).
- WHEN `value` is `int` `0` or `1` THEN it SHALL be **false** — a verdict must be a genuine
  boolean, not a truthy integer.

### Dict / per_repo coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- WHEN `items` is `None` or an empty list THEN `_per_repo_list` SHALL return `[]` **silently**.
- WHEN `items` is a non-list THEN it SHALL **emit a warning** and return `[]` (never coerced).
- `_per_repo_list` SHALL keep only `dict` entries (non-dict entries are dropped; unlike the
  check-rows helper it does **not** warn per entry).

### Check-row field & sanitation

- `_check_row_field("name", v)` SHALL be true only for a non-empty (post-`strip`) `str`;
  `_check_row_field("passed", v)` SHALL be `_is_passed(v)`; any other key SHALL be false.
- `_check_rows_list` SHALL return `[]` for `None` and for an empty list, both silently.
- WHEN `checks` is a non-list THEN it SHALL warn and return `[]`.
- A row SHALL be skipped **with a warning** when it is not a dict, is missing any
  `_CHECK_ROW_KEYS` key, or fails `_check_row_field` for `name` or `passed`.
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Tally & stats helpers

- `_tally_counts(tally)` SHALL return `None` when `tally` is not a dict or any of
  `_TALLY_KEYS` is absent or fails `_is_number`; otherwise a dict of `int(...)` counts.
- `_stats_dual_order_tasks(stats)` SHALL return `int(dual_order_tasks)` when that field passes
  `_is_number`; OTHERWISE the `int` sum of `agree` + `disagree` + `tie` when **all three** pass
  `_is_number`; OTHERWISE `None`.
- `_expected_disagreement_rate(stats)` SHALL return `round(disagree / dual, 3)` only when the
  dual-order total is truthy-positive and `disagree` passes `_is_number`; OTHERWISE `None`.

### Slice detection (`_slice_has_judge_telemetry`, `_expand_slice`, `_report_slices`)

- A slice SHALL be considered to carry judge telemetry when: `tasks` passes `_is_number` and
  `int(tasks) > 0`; OR `judge_report`/`judge_order_stats` is not `None`; OR `scored_repos`
  passes `_is_number` and `int(...) > 0`.
- `_expand_slice` SHALL check `per_repo` **first**: WHEN `part` has no `per_repo` key it SHALL
  yield `[(label, part)]` only if the part itself carries `judge_report`/`judge_order_stats`,
  else `[]`; OTHERWISE it SHALL yield one slice per `per_repo` row that has judge telemetry,
  labelled `{label}:repo-{index}`.
- WHEN `result` carries dict `tuned` and `held_out` AND a `generalization_gap` key THEN each
  `_partition_scored` partition SHALL contribute its slices, labelled `tuned` / `held_out`.
- OTHERWISE WHEN `result` has a `per_repo` key THEN each telemetry-bearing entry SHALL be a slice
  labelled `repo-{index}`.
- OTHERWISE WHEN `result` itself carries telemetry THEN it SHALL be one slice labelled `run`
  (whose check names carry **no** prefix); else `_report_slices` SHALL return `[]`.

### Per-slice checks (`_check_slice`)

For a slice labelled `L`, check names SHALL be prefixed `L:` unless `L == "run"`.

- `report_present` SHALL pass iff `judge_report` is a dict (detail names the offending value when
  not); `stats_present` SHALL pass iff `judge_order_stats` is a dict.
- WHEN the report is a dict AND `tally` resolves via `_tally_counts` THEN for each
  `_REPORT_TALLY`→`_TALLY_KEYS` pair a `{key}_match_tally` check SHALL pass iff the report count
  passes `_is_number` and `int(...)` equals the tally count.
- WHEN the report is a dict but there is no usable tally THEN each `{key}_match_tally` SHALL pass
  with detail `"no tally to compare for {key}"`.
- WHEN both report and stats are dicts THEN:
  - `dual_order_tasks_match` SHALL pass iff `_stats_dual_order_tasks` is not `None` and the
    report's `dual_order_tasks` passes `_is_number` and equals it;
  - `disagreements_match` SHALL pass iff both `stats.disagree` and `report.disagreements` pass
    `_is_number` and their `int(...)` are equal;
  - `disagreement_rate_matches` SHALL pass when both expected rate and report rate are `None`
    (`"no dual-order tasks; rate n/a"`); pass iff equal when both are available; else **fail**
    with a `"cannot compare disagreement_rate (...)"` detail.
- WHEN the report is a dict but stats is **not** THEN `dual_order_tasks_match`,
  `disagreements_match` and `disagreement_rate_matches` SHALL each be added as **failing** with
  detail `"cannot compare without judge_order_stats"`.

### per_repo well-formedness (`_malformed_per_repo_rows`)

- WHEN the artifact carries no `per_repo` container THEN it SHALL return `None` and the
  `per_repo_rows_wellformed` check SHALL NOT be added.
- WHEN a `per_repo` list exists THEN each **non-empty string** entry SHALL be flagged
  `repo-{index}` (or `{partition}:repo-{index}` for generalization); dicts (including ones
  carrying their own `error`), ints, `None`, lists and blank strings SHALL NOT be flagged.
- The check SHALL pass with detail `"all per_repo rows are well-formed result objects"` when
  nothing is flagged, else `"corrupt per_repo string row(s): {labels}"`.

### Top-level result (`check_judge_report_integrity`)

- WHEN `result` is not a `dict` THEN the result SHALL be `{"passed": False, "checks": [...]}`
  carrying only a failing `artifact_shape` with detail
  `"artifact must be a JSON object, got {type}"`, and slices SHALL NOT be evaluated.
- WHEN `_report_slices` yields nothing THEN a failing `artifact_shape` SHALL be added with detail
  `"no scored replay slice with judge telemetry to verify"`.
- The returned mapping SHALL carry exactly `passed` and `checks`; `passed` SHALL be
  `all(c["passed"] for c in checks)`.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized row whose `passed` is falsy,
  over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `integrity_headline` SHALL be exactly:
  `judge report integrity: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be:
  `judge report integrity: CONSISTENT ({n} checks passed)`.
- OTHERWISE it SHALL be:
  `judge report integrity: INCONSISTENT ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_judge_report_integrity()` SHALL NOT mutate its input.

## Out of scope

- Whether the judge was robust enough to gate on (`judge_gate`).
- The blend weights (`weight_integrity`, Spec 062) and anchor inputs (`objective_integrity`,
  Spec 061).

## Verification

- `tests/test_spec_063_judge_report_integrity.py` exercises each EARS block above, including
  `_is_number` rejecting `decimal.Decimal` / bool / non-finite / oversized-int, **warning
  emission** for every warn branch, the `_is_passed` numpy typenames and int-rejection, both
  `_check_slice` telemetry branches, empty/missing slices, and every headline branch.
- Broader coverage (including the CLI) remains in `tests/test_judge_report_integrity.py`.
