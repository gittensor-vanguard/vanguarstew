# Spec 064 — repeatability gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1879
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repeatability.py`](../../benchmark/repeatability.py) (the spread/CV
  metrics this gate consumes), [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) and
  [`benchmark/run_clean.py`](../../benchmark/run_clean.py) (sibling pass/fail gates),
  [`scripts/repeatability_gate.py`](../../scripts/repeatability_gate.py) (the CI entry point)

This spec makes the **existing, implicit** repeatability-gate contract explicit. It describes the
as-built behavior of `benchmark/repeatability_gate.py`; it introduces **no behavior change**.

## Why

`assess_repeatability` reports spread/CV metrics for repeated runs of the same config (ROADMAP M1:
"re-runs are stable"); `check_repeatability` is the **pass/fail gate** that names each criterion
for CI logs, mirroring `check_judge` / `check_run_clean`. `scripts/repeatability_gate.py` exits
non-zero when any check fails, so the exact pass condition and detail string of each named check
is a CI contract worth pinning.

## Recorded divergences — and why they are tolerated here

### 1. `_is_number` has no finiteness or overflow guard

Every recent sibling gate's `_is_number` rejects non-finite values and guards `OverflowError`
(`judge_gate`, `judge_report_integrity`, `weight_integrity`, `objective_integrity`). This
module's does **not**:

```python
def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
```

Verified consequences of the as-built code (all pinned by tests):

```
>>> _is_number(float("nan")), _is_number(float("inf")), _is_number(10**400)
(True, True, True)
>>> repeatability_gate_headline({"passed": True, "checks": [ok], "runs": 2, "cv": float("nan")})
'repeatability gate: STABLE (2 runs, cv nan%)'
>>> repeatability_gate_headline({..., "cv": float("inf")})
'repeatability gate: STABLE (2 runs, cv inf%)'
>>> repeatability_gate_headline({..., "cv": float("-inf")})
'repeatability gate: STABLE (2 runs, cv -inf%)'
>>> repeatability_gate_headline({..., "cv": 10**400})
OverflowError: int too large to convert to float
```

**Why this is tolerable here, unlike in the siblings.** In the integrity gates, `_is_number`
admits *externally loaded* artifact fields into pass/fail decisions, so a `NaN`/`inf` that
slipped through would flip a gate verdict — those modules must fail closed. In this module
`_is_number` guards only **presentation**: it selects between the `"cv {cv}"` /
`"cv {cv} <= max_cv {max_cv}"` detail strings and their fallbacks, and between `f"{cv:.1%}"` and
`"n/a"` in the headline. The pass/fail verdicts themselves key off `assess_repeatability`'s
`stable` / `cv is None` logic upstream. In the composed pipeline a non-finite or oversized `cv`
**cannot occur**: every score entering the spread math is admitted by
`benchmark.trend.headline_score`, whose own `_is_number` applies `math.isfinite` and catches
`OverflowError`, so `assess_repeatability` only ever emits a `cv` of `None`, `0.0`, or a finite
rounded ratio of finite numbers. Reaching the behaviors above therefore requires a **hand-built
result dict passed straight to the formatter**, where the blast radius is a cosmetic
`cv nan%` / `cv inf%` string — or an `OverflowError` out of a diagnostic helper — never a wrong
gate verdict or exit code. Adding the guard would visibly change output (`cv nan%` → `cv n/a`),
which is a behavior change and out of scope for this documentation-only spec; the exposure is
recorded and test-pinned here so a future hardening PR can cite it.

### 2. Check-row sanitation accepts an empty `name` and rejects numpy booleans

`_check_rows_list` requires only `isinstance(row["name"], str)` — an **empty** `name` survives,
unlike `judge_gate._check_row_field` / `run_clean._check_row_field`, which require a non-empty
`str`. Conversely `type(row["passed"]) is not bool` rejects a numpy scalar bool that the newer
siblings (with `_NUMPY_BOOL_TYPENAMES`-style allowances) accept. Both are tolerable for the same
reason as above: sanitation here feeds only the *presentation-layer* helpers (`failed_checks`,
the headline counts), and every row `check_repeatability` itself emits is a well-formed native
dict with a non-empty `name` and a native `bool` — the divergent arms are reachable only from
hand-built results, where an empty name renders harmlessly in the failure list and a rejected
numpy verdict merely drops the row from a diagnostic string. Both arms are pinned by tests.

## User stories

1. **As a CI maintainer**, I can gate on `scripts/repeatability_gate.py` and know exactly which
   named check failed and why, from stable detail strings.
2. **As a benchmark operator**, I can read a stable `repeatability_gate_headline()` STABLE /
   UNSTABLE line in CI logs.
3. **As a reviewer**, every malformed-input, empty, warning, non-finite and headline branch is
   written down (addressing the incompleteness class of rejection seen on Specs 057/059/061/062
   and the closed first attempt at this spec, whose `inf`/`-inf`/oversized-int headline
   consequences were recorded but not test-pinned).

## Constants

- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.
- Defaults SHALL be imported from `benchmark.repeatability`: `DEFAULT_MAX_CV` (`0.05`) and
  `DEFAULT_MIN_RUNS` (`2`).
- `_effective_min_runs` (imported) SHALL return `DEFAULT_MIN_RUNS` for a `bool` or non-`int`
  `min_runs` (`True`, `"3"`, `None`, `2.0` → `2`), else `max(0, min_runs)` — so
  `_effective_min_runs(0) == 0`, `_effective_min_runs(-5) == 0`, `_effective_min_runs(3) == 3`.

## Acceptance criteria (EARS)

### Helpers

- `_is_number(value)` SHALL be true iff `isinstance(value, (int, float))` and `value` is not a
  `bool`. It SHALL perform **no** finiteness or overflow check (see *Recorded divergences*):
  `NaN`, `inf`, `-inf` and an oversized `int` (`10**400`) SHALL all be true; `Decimal`,
  `Fraction`, `str`, `None`, `list`, `dict` and both `bool` values SHALL be false.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Result shape (`check_repeatability`)

- The result SHALL carry `passed`, `checks`, and the spread metrics copied from
  `assess_repeatability`: `runs`, `scores`, `mean`, `stddev`, `cv`, `min`, `max`, `range`,
  `max_cv`, `min_runs`, `reason`.
- `passed` SHALL be `all(c["passed"] for c in checks)`.
- The five checks SHALL be emitted in this order: `artifacts_is_list`, `scored_runs`,
  `enough_repeats`, `cv_defined`, `spread_acceptable`; every check row SHALL carry `name`,
  `passed` (a native `bool`) and `detail`.

### `artifacts_is_list`

- SHALL pass iff `isinstance(artifacts, list)`.
- WHEN it passes THEN the detail SHALL be `"{n} artifact(s) in a list"` where `n` is the list's
  length.
- OTHERWISE the detail SHALL be `"artifacts is {type}, expected a list"`, the non-list input
  SHALL be treated as empty (so the remaining checks evaluate against zero runs rather than
  raising), and the underlying coercion SHALL log a warning on the `benchmark.repeatability`
  logger.

### `scored_runs`

- SHALL pass iff the summary's `runs` is greater than `0` (`runs` counts artifacts whose
  `headline_score` is not `None`).
- Detail SHALL be `"{runs} scored repeat(s)"` when passing, else
  `"no artifact carried a usable headline score"`.

### `enough_repeats`

- SHALL pass iff `runs >= _effective_min_runs(min_runs)`.
- Detail SHALL be `"{runs} scored >= min_runs {required}"` whenever `runs > 0` — **including on
  failure** (e.g. `"1 scored >= min_runs 3"` with `passed` false) — else
  `"need at least {required} scored repeat(s)"`.
- WHEN `min_runs` is non-positive THEN `required` is `0`, so any run count (including `0`)
  SHALL satisfy this check (while `scored_runs` still fails a zero-run set).

### `cv_defined`

- SHALL pass when the summary's `cv` is not `None`, **OR** when `stddev == 0` and `runs > 0` and
  `runs >= required` (identical runs are a defined zero-spread case).
- Detail SHALL be `"cv {cv}"` when `_is_number(cv)`, else the summary's `reason` when non-empty,
  else `"coefficient of variation unavailable"`.
- WHEN the scores have a zero mean with nonzero spread THEN `cv` is `None` and this check SHALL
  fail with the detail `"coefficient of variation undefined (zero mean with nonzero spread)"`.

### `spread_acceptable`

- SHALL pass iff the summary's `stable` is truthy.
- Detail SHALL be `"cv {cv} <= max_cv {max_cv}"` when `_is_number(cv)` **and** the check passes;
  OTHERWISE the summary's `reason` when non-empty (e.g. `"cv 1.132 exceeds max_cv 0.05"`, or a
  `"repeat {i} not clean: …"` early-exit reason), else
  `"spread not acceptable (cv {cv!r}, max_cv {max_cv})"` (reachable only from a hand-built
  summary, since `assess_repeatability` always sets a reason when not stable).

### Check-row sanitation (`_check_rows_list`)

- `None` SHALL yield `[]` silently; an empty list SHALL yield `[]` silently.
- WHEN `checks` is a non-list THEN it SHALL **emit a warning** and return `[]` (never coerced).
- A row SHALL be skipped **with a warning** when it is not a dict, is missing any
  `_CHECK_ROW_KEYS` key, has a non-`str` `name`, or has a `passed` whose
  `type(...) is not bool` — so a truthy `int` `1` is rejected, a numpy scalar bool is rejected,
  while an **empty-`str` `name` survives** (see *Recorded divergences*).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.
- All warnings SHALL be emitted on the `benchmark.repeatability_gate` logger.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized row whose `passed` is
  falsy, over `_dict(result).get("checks")` — a non-dict `result` SHALL yield `[]`.
- WHEN no sanitized check rows exist (a non-dict result, a missing / non-list / empty `checks`,
  or rows that all fail sanitation) THEN `repeatability_gate_headline` SHALL be exactly
  `repeatability gate: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `repeatability gate: STABLE ({runs} runs, cv {cv_txt})`, where `cv_txt` is `f"{cv:.1%}"` when
  `_is_number(cv)` else `n/a`. Consequences, all pinned: a `None` cv renders `cv n/a`; a `NaN`
  cv renders `cv nan%`, `inf` / `-inf` render `cv inf%` / `cv -inf%`, and an oversized-`int` cv
  raises `OverflowError` (the recorded divergence); a missing `runs` renders literally as
  `None runs` (raw interpolation, diagnostic-path cosmetic).
- OTHERWISE it SHALL be `repeatability gate: UNSTABLE ({f}/{n} checks failed: {names})`, where
  both `f` and `n` count **sanitized** rows only (a malformed row is excluded from both counts).

### Pure evaluation

- The module SHALL perform no I/O.
- `check_repeatability()` SHALL NOT mutate its input, and any malformed input SHALL fail the
  relevant checks rather than raise.

## Out of scope

- The spread metrics themselves (`benchmark/repeatability.py`) and the headline-score extraction
  (`benchmark/trend.py`).
- Adding the finiteness/`OverflowError` guard to `_is_number`, or aligning the sanitation's
  empty-name / numpy-bool arms with the siblings (recorded above as divergences; changing either
  would be a behavior change).
- The CLI exit-code mapping (`scripts/repeatability_gate.py`), covered by
  `tests/test_repeatability_gate.py`.

## Verification

- `tests/test_spec_064_repeatability_gate.py` exercises each EARS block above with **literal**
  expected strings, including: the recorded `_is_number` divergence and **every** headline
  consequence (`nan%`, `inf%`, `-inf%`, the `OverflowError` raise, `n/a`, `None runs`), the
  zero-mean undefined-CV branch, the non-list coercion and its warning, the non-positive and
  non-`int` `min_runs` arms, every check's pass **and** fail detail, warning **emission** for
  each sanitation warn branch, the empty-name acceptance, the `int`-verdict and numpy-bool
  rejections, and the sanitized-rows-only headline counts.
- Broader coverage (including the CLI) remains in `tests/test_repeatability_gate.py`.
