# Spec 036 — skip budget gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #989
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/skip_budget.py`](../../benchmark/skip_budget.py) (this gate),
  [`benchmark/skip_share.py`](../../benchmark/skip_share.py) (skip-share report, Spec 043),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind)

This spec makes the **existing, implicit** skip-budget contract explicit. It describes the
as-built behavior of `benchmark/skip_budget.py`; it introduces **no behavior change**.

## Why

`run_multi_replay` scores the repos that clone, build, and produce tasks; the rest are *skipped*.
The headline composite is a mean over the repos that *did* score, so a run that quietly dropped the
hard repos can report a strong mean over a small, biased subset. `check_skip_budget` gates the run
*outcome* — enough repos actually scored and the skip rate stayed within budget — so an
under-covered run fails closed instead of masquerading as trustworthy.

## User stories

1. **As a benchmark operator**, I can gate a multi-repo run on coverage before trusting its mean.
2. **As a CI maintainer**, I can log a stable `skip_budget_headline()` string alongside the JSON
   result and exit non-zero via `scripts/skip_budget.py` when too many repos were skipped.
3. **As a reviewer**, the malformed-input handling, fail-closed semantics, and every headline branch
   are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the `result` is not a `dict` THEN `check_skip_budget(result)` SHALL treat it as `{}` and
  evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number repo counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values (including whole floats such as `3.0`) SHALL NOT be treated as integers.

### Boolean semantics (`_is_bool`)

- `_is_bool` SHALL be true for `True`/`False` (and `bool` subclasses).
- `_is_bool` SHALL be false for `int` `0`/`1` and every non-`bool` value.

### Multi-repo accounting (`_counts`)

- WHEN `repos` and `scored_repos` both pass `_is_int`, AND `repos > 0`, AND
  `0 <= scored_repos <= repos`, AND (a `skipped` field, when present, passes `_is_int` and equals
  `repos - scored_repos`) THEN `_counts(result)` SHALL return `(repos, scored_repos)`.
- WHEN any of those conditions fails — non-`int` `repos`/`scored_repos`, `repos <= 0`,
  `scored_repos < 0`, `scored_repos > repos`, or a present `skipped` that is non-`int` or not equal
  to `repos - scored_repos` — THEN `_counts` SHALL return `None`.

### Gate evaluation (`check_skip_budget`)

The result SHALL always include: `passed`, `checks`, `repos`, `scored_repos`, `skipped`,
`skip_rate`, `min_scored`, `max_skip_rate`.

- `checks` SHALL always report exactly three rows, in order:
  `multi_repo_accounting`, `enough_scored`, `skip_within_budget`; each row is
  `{name, passed, detail}` with a `bool` `passed`.
- `multi_repo_accounting` SHALL pass iff `_counts(result)` is not `None`.
- `enough_scored` SHALL pass iff the tally is coherent AND `scored_repos >= min_scored`
  (inclusive).
- `skip_within_budget` SHALL pass iff `skip_rate` is available AND `skip_rate <= max_skip_rate`
  (inclusive).
- WHEN the tally is coherent THEN `skipped` SHALL be `repos - scored_repos` and `skip_rate` SHALL
  be `round(skipped / repos, 3)`; OTHERWISE `skipped` and `skip_rate` SHALL be `None` and the
  `enough_scored`/`skip_within_budget` checks SHALL fail closed.
- `passed` SHALL be `True` iff every check passed.
- The default thresholds SHALL be `min_scored = 3` (`DEFAULT_MIN_SCORED`) and
  `max_skip_rate = 0.25` (`DEFAULT_MAX_SKIP_RATE`).

### Checks-row sanitization (`_check_rows_list`)

- `None` (absent key) and an empty list SHALL yield `[]` silently.
- A non-list container (scalar, dict, tuple, string, …) SHALL be warned and treated as empty
  (never coerced or iterated).
- A row that is not a `dict`, a row missing `name` or `passed`, a row whose `name` is not a
  `str`, or a row whose `passed` is not a `bool` SHALL each be skipped with a warning.
- WHEN a non-empty `checks` yields no usable rows THEN a warning SHALL be logged.

### Failed checks (`failed_checks`)

- `failed_checks(result)` SHALL return the `name` of each usable row whose `passed` is falsey,
  routed through `_check_rows_list` so a malformed `checks` container or unusable rows are skipped
  rather than raising.

### Skip budget headline (`skip_budget_headline`)

- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be `skip budget: no checks evaluated`.
- WHEN `passed` is truthy THEN the headline SHALL be
  `skip budget: COVERED ({scored_repos} of {repos} repos scored, skip rate {skip_rate})`.
- OTHERWISE the headline SHALL be
  `skip budget: UNDER-COVERED ({failed}/{total} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_skip_budget()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_036_skip_budget.py` exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_skip_budget.py`.
