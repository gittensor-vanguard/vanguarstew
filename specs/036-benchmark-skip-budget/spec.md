# Spec 036 — skip budget gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #989
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (repo coverage summary),
  [`benchmark/repo_set_readiness.py`](../../benchmark/repo_set_readiness.py) (repo-set config gate),
  [`benchmark/sample_adequacy.py`](../../benchmark/sample_adequacy.py) (checks-row sanitization pattern)

This spec makes the **existing, implicit** skip-budget contract explicit. It describes the
as-built behavior of `benchmark/skip_budget.py`; it introduces **no behavior change**. A multi-repo
run that skipped most of its declared repos can still report a healthy composite mean — that
coverage gate must be written down and verified.

## Why

`run_multi_replay` reports `repos`, `scored_repos`, and (optionally) `skipped`, but nothing gates
whether enough repos actually scored. `check_skip_budget()` is the reproducible pass/fail gate;
making its contract explicit lets reviewers check skip-budget changes against intent.

## User stories

1. **As a benchmark operator**, I can verify a multi-repo run scored enough repos before trusting
   its composite mean.
2. **As a CI maintainer**, I can gate on `check_skip_budget()` with a stable headline string.
3. **As a reviewer**, malformed-input handling, extra dict keys, and every headline branch are
   written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_MIN_SCORED = 3` as the default minimum scored-repo count for
  `check_skip_budget(result, min_scored=...)`.
- The module SHALL expose `DEFAULT_MAX_SKIP_RATE = 0.25` as the default maximum skipped fraction
  for `check_skip_budget(result, max_skip_rate=...)`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number repo counts.
- `bool` SHALL NOT be treated as an integer (avoids truthy counts).
- `float` values — including whole-number floats such as `8.0` — SHALL NOT be treated as integers.
- NumPy integer scalars (e.g. `numpy.int64`) SHALL NOT be treated as integers (only built-in
  `int` passes `_is_int`).

### Input coercion

- WHEN the run `result` is not a `dict` THEN `check_skip_budget(result)` SHALL treat it as `{}`
  and evaluate checks (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- Extra keys on the input `result` dict (fields other than `repos`, `scored_repos`, and
  `skipped`) SHALL be ignored and SHALL NOT affect gate evaluation.

### Multi-repo accounting (`_counts`)

- WHEN both `repos` and `scored_repos` pass `_is_int` AND `repos > 0` AND `0 <= scored_repos <=
  repos` AND (when `skipped` is present) `skipped` passes `_is_int` and equals
  `repos - scored_repos` THEN `_counts` SHALL return `(repos, scored_repos)`.
- WHEN `skipped` is absent THEN `_counts` SHALL succeed on valid `repos`/`scored_repos` alone.
- WHEN `repos <= 0` THEN `_counts` SHALL return `None`.
- WHEN `scored_repos < 0` THEN `_counts` SHALL return `None`.
- WHEN `scored_repos > repos` THEN `_counts` SHALL return `None`.
- WHEN either count fails `_is_int` THEN `_counts` SHALL return `None`.
- WHEN `skipped` is present but not a whole number equal to `repos - scored_repos` THEN
  `_counts` SHALL return `None`.

### Skip rate

- WHEN `_counts` returns a pair THEN `check_skip_budget` SHALL set `skipped = repos - scored_repos`
  and `skip_rate = round(skipped / repos, 3)`.
- WHEN `_counts` returns `None` THEN `skip_rate` SHALL be `None` (distinct from `0.0` for a
  full-coverage run).
- WHEN `skipped == 0` and `_counts` succeeds THEN `skip_rate` SHALL be `0.0`.

### Gate checks

`check_skip_budget(result, min_scored=..., max_skip_rate=...)` SHALL always report exactly three
checks in this order:

1. **`multi_repo_accounting`** — passes when `_counts` is not `None`; detail is
   `"{scored} of {repos} repo(s) scored, {skipped} skipped"` on success, otherwise
   `"no coherent multi-repo tally (repos / scored_repos / skipped)"`.
2. **`enough_scored`** — passes when counts are coherent and `scored_repos >= min_scored`; detail is
   `"{scored} scored repo(s) >= {min_scored}"` when counts are coherent, otherwise
   `"scored-repo count unavailable"`.
3. **`skip_within_budget`** — passes when `skip_rate` is not `None` and `skip_rate <= max_skip_rate`;
   detail is `"skip rate {skip_rate} <= {max_skip_rate}"` when `skip_rate` is available, otherwise
   `"skip rate unavailable"`.

Each check SHALL include `name`, `passed` (bool), and `detail` (str). The skip-rate bound is
**inclusive** (`skip_rate == max_skip_rate` passes).

### Gate result shape

Every gate result SHALL always include these keys (never omitted):

| Key | Always present | Value when unavailable |
| --- | --- | --- |
| `passed` | yes | `False` when any check fails |
| `checks` | yes | list of three check dicts |
| `repos` | yes | `None` when accounting incoherent |
| `scored_repos` | yes | `None` when accounting incoherent |
| `skipped` | yes | `None` when accounting incoherent |
| `skip_rate` | yes | `None` when accounting incoherent (not `0.0`) |
| `min_scored` | yes | echoes the parameter |
| `max_skip_rate` | yes | echoes the parameter |

Extra keys on a gate **result** dict passed to `skip_budget_headline()` or `failed_checks()` SHALL
be ignored (only documented keys above and the `checks` list influence output).

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN `checks` is `None` or `[]` THEN `_check_rows_list()` SHALL return `[]` without warning.
- WHEN a check row is not a `dict`, lacks required keys, has a non-`str` `name`, or has a
  non-`bool` `passed` THEN that row SHALL be skipped with a warning.
- WHEN every row in a non-empty `checks` list is unusable THEN `_check_rows_list()` SHALL log a
  warning that no usable rows remain.
- `failed_checks(result)` SHALL return the `name` of each usable row whose `passed` is not truthy.
- WHEN `checks` is missing, empty, or only unusable rows THEN `failed_checks()` SHALL return `[]`.

### Skip budget headline

`skip_budget_headline(result)` SHALL return a one-line human summary.

- WHEN the input is not a `dict` THEN it SHALL be coerced via `_dict`.
- IF no usable check rows remain after sanitization THEN the headline SHALL be exactly:
  `skip budget: no checks evaluated` — regardless of the top-level `passed` flag.
- WHEN usable checks exist and `result["passed"]` is true THEN the headline SHALL be exactly:
  `skip budget: COVERED ({scored_repos} of {repos} repos scored, skip rate {skip_rate})` where
  `{scored_repos}`, `{repos}`, and `{skip_rate}` are the values from the result dict (a passing
  gate from `check_skip_budget` always supplies numeric counts and a numeric `skip_rate`, including
  `0.0` for full coverage).
- WHEN usable checks exist and `result["passed"]` is false THEN the headline SHALL be exactly:
  `skip budget: UNDER-COVERED ({failed_count}/{total_checks} checks failed: {names})` where
  `{names}` is the comma-separated list of failed check names from `failed_checks(result)`.

Exact examples (character-for-character):

| Condition | Expected headline |
| --- | --- |
| `passed=True`, `scored_repos=8`, `repos=8`, `skip_rate=0.0` | `skip budget: COVERED (8 of 8 repos scored, skip rate 0.0)` |
| `passed=True`, `scored_repos=7`, `repos=8`, `skip_rate=0.125` | `skip budget: COVERED (7 of 8 repos scored, skip rate 0.125)` |
| `passed=False`, one failed check `enough_scored` | `skip budget: UNDER-COVERED (1/3 checks failed: enough_scored)` |
| `passed=False`, three failed checks | `skip budget: UNDER-COVERED (3/3 checks failed: multi_repo_accounting, enough_scored, skip_within_budget)` |
| No usable check rows | `skip budget: no checks evaluated` |
| Non-dict input | `skip budget: no checks evaluated` |

The headline SHALL NOT contain the bare substring `None` for a gate result produced by
`check_skip_budget()` (fields are either numeric or omitted from the COVERED/UNDER-COVERED
templates via the no-checks branch).

### Pure evaluation

- The module SHALL perform no I/O.
- `check_skip_budget()` SHALL NOT mutate its input dict.

## Out of scope

- Repo-set configuration readiness (`benchmark/repo_set_readiness.py`).
- Scored-fraction summary (`benchmark/scored_fraction.py`).
- Changing `run_multi_replay` repo accounting semantics.

## Verification

- `tests/test_spec_036_skip_budget.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_skip_budget.py`.
