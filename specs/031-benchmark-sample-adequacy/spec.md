# Spec 031 — sample adequacy gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #911
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/tally_integrity.py`](../../benchmark/tally_integrity.py) (tally sum checks),
  [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (composite blend checks)

This spec makes the **existing, implicit** sample-adequacy contract explicit. It describes the
as-built behavior of `benchmark/sample_adequacy.py`; it introduces **no behavior change**. A replay
with too few tasks or an incomplete tally must not flow into trend/leaderboard output as if it were
a full run — that gate must be written down and verified.

## Why

`run_eval` reports task counts, but nothing stops a headline computed from a handful of tasks — or
one where tasks vanished between judging and tallying — from being treated as trustworthy.
`check_sample_adequacy()` is the reproducible pass/fail gate; making its contract explicit lets
reviewers check sample-adequacy changes against intent.

## User stories

1. **As a benchmark operator**, I can verify a replay judged and accounted for enough tasks before
   trusting compare/trend output.
2. **As a CI maintainer**, I can gate on `check_sample_adequacy()` with a stable headline string.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_MIN_TASKS = 3` as the default minimum task count for
  `check_sample_adequacy(result, min_tasks=...)`.

### Numeric semantics

- Only built-in `int`/`float` values SHALL count as numeric for task totals and tally counts.
- `bool` SHALL NOT be treated as numeric (avoids truthy counts).

### Input coercion

- WHEN the run `result` is not a `dict` THEN `check_sample_adequacy(result)` SHALL treat it as `{}`
  and evaluate checks (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Task total (`_total_tasks`)

- WHEN the top-level `tasks` field is numeric THEN the total SHALL be that value (single-repo).
- WHEN `per_repo` lists appear (top-level or under `tuned` / `held_out` generalization
  partitions) THEN the total SHALL be the sum of numeric `tasks` on every dict row in every list.
- WHEN any `per_repo` entry is missing, not a list, empty, or contains a non-dict row or a row
  without a numeric `tasks` field THEN `_total_tasks` SHALL return `None` (fail closed).

### Tally accounting (`_decided`)

- WHEN `tally` is not a `dict` THEN `_decided` SHALL return `None`.
- WHEN `tally` is a `dict` but any of `challenger`, `baseline`, or `tie` is missing or
  non-numeric THEN `_decided` SHALL return `None`.
- WHEN all three tally keys are numeric THEN `_decided` SHALL return their sum.

### Gate checks

`check_sample_adequacy(result, min_tasks=...)` SHALL always report exactly three checks:

1. **`run_scored`** — passes when the result has no `error`, the task total is numeric and
   strictly greater than zero;
2. **`enough_tasks`** — passes when the task total is numeric and `tasks >= min_tasks`;
3. **`all_tasks_decided`** — passes when `_decided` is not `None` and equals the task total.

Each check SHALL include `name`, `passed` (bool), and `detail` (str).

### Gate result shape

- The gate SHALL return `{"passed", "checks", "tasks", "decided", "min_tasks"}` where `passed` is
  `True` only when every check passes.
- `tasks` SHALL be the numeric total when available, otherwise `None`.
- `decided` SHALL be the tally sum when complete, otherwise `None`.
- `min_tasks` SHALL echo the parameter passed to the gate.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN `checks` is `None` or `[]` THEN `_check_rows_list()` SHALL return `[]` without warning.
- WHEN a check row is not a `dict` THEN that row SHALL be skipped with a warning.
- WHEN every row in a non-empty `checks` list is unusable THEN `_check_rows_list()` SHALL log a
  warning that no usable rows remain.
- `failed_checks(result)` SHALL return the `name` of each usable row whose `passed` is not truthy.
- WHEN `checks` is missing, empty, or only unusable rows THEN `failed_checks()` SHALL return `[]`.

### Sample adequacy headline

- `sample_adequacy_headline(result)` SHALL return a one-line human summary.
- IF no usable check rows remain after sanitization THEN the headline SHALL read
  `sample adequacy: no checks evaluated` — regardless of the top-level `passed` flag.
- WHEN usable checks exist and `result["passed"]` is true THEN the headline SHALL include
  `ADEQUATE` and the task count; when `tasks` is non-numeric the count SHALL display as `n/a`.
- WHEN usable checks exist and `result["passed"]` is false THEN the headline SHALL include
  `INADEQUATE`, the count of failed checks versus usable checks, and the failed check names.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_sample_adequacy()` SHALL NOT mutate its input dict.

## Out of scope

- Per-task tally recomputation (`benchmark/tally_integrity.py`).
- Composite-score blend checks (`benchmark/score_integrity.py`).
- Changing `run_replay` / `run_multi_replay` task accounting semantics.

## Verification

- `tests/test_spec_031_sample_adequacy.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_sample_adequacy.py`.
