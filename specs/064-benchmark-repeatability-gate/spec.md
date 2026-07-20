# Spec 064 — repeatability gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1879
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repeatability.py`](../../benchmark/repeatability.py) (the spread/CV
  metrics this gate consumes), [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) and
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (sibling pass/fail gates)

This spec makes the **existing, implicit** repeatability-gate contract explicit. It describes the
as-built behavior of `benchmark/repeatability_gate.py`; it introduces **no behavior change**.

## Why

`assess_repeatability` reports spread/CV metrics for repeated runs of the same config;
`repeatability_gate` is the **pass/fail gate** that names each criterion for CI logs, mirroring
`check_judge` / `check_promotion`. `scripts/repeatability_gate.py` exits non-zero when any check
fails, so the exact pass condition of each named check is a CI contract worth pinning.

## A divergence worth recording

Every sibling gate's `_is_number` rejects non-finite values and guards `OverflowError`
(`objective_integrity`, `judge_report_integrity`, `weight_integrity`, `tally_integrity`). This
module's does **not** — it is only:

```python
def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
```

Verified consequences of the as-built code:

```
>>> _is_number(float("nan")), _is_number(float("inf")), _is_number(10**400)
(True, True, True)
>>> repeatability_gate_headline({"passed": True, "checks": [...], "runs": 2, "cv": float("nan")})
'repeatability gate: STABLE (2 runs, cv nan%)'
>>> repeatability_gate_headline({... "cv": 10**400})
OverflowError: int too large to convert to float
```

So a `NaN` cv renders as `cv nan%`, and an oversized-int cv raises `OverflowError` out of the
headline formatter. This spec documents the **as-built** behavior and records the divergence;
changing `_is_number` is deliberately **out of scope** so this stays documentation-only.

## User stories

1. **As a CI maintainer**, I can gate on `scripts/repeatability_gate.py` and know exactly which
   named check failed.
2. **As a benchmark operator**, I can read a stable `repeatability_gate_headline()` string.
3. **As a reviewer**, every malformed-input, empty, warning and headline branch is written down
   (addressing the incompleteness class of rejection seen on Specs 057/059/061/062).

## Constants

- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.
- Defaults SHALL come from `benchmark.repeatability`: `DEFAULT_MAX_CV` (`0.05`) and
  `DEFAULT_MIN_RUNS` (`2`).
- `_effective_min_runs` (imported) SHALL floor a non-positive `min_runs` to `0`
  (`_effective_min_runs(0) == 0`, `_effective_min_runs(-5) == 0`, `_effective_min_runs(3) == 3`).

## Acceptance criteria (EARS)

### Helpers

- `_is_number(value)` SHALL be true iff `isinstance(value, (int, float))` and `value` is not a
  `bool`. It performs **no** finiteness or overflow check (see *A divergence worth recording*):
  `NaN`, `inf`, `-inf` and an oversized `int` SHALL all be true; `Decimal`, `str`, `None`, list
  and dict SHALL be false.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Result shape (`check_repeatability`)

- The result SHALL carry `passed`, `checks`, and the spread metrics copied from
  `assess_repeatability`: `runs`, `scores`, `mean`, `stddev`, `cv`, `min`, `max`, `range`,
  `max_cv`, `min_runs`, `reason`.
- `passed` SHALL be `all(c["passed"] for c in checks)`.
- The five checks SHALL be emitted in this order: `artifacts_is_list`, `scored_runs`,
  `enough_repeats`, `cv_defined`, `spread_acceptable`.
- `check_repeatability` SHALL NOT mutate its input and SHALL perform no I/O.

### `artifacts_is_list`

- SHALL pass iff `isinstance(artifacts, list)`.
- WHEN it passes THEN the detail SHALL be `"{n} artifact(s) in a list"` where `n` is the length
  of the coerced artifact list.
- OTHERWISE the detail SHALL be `"artifacts is {type}, expected a list"`, and the non-list input
  SHALL be coerced to empty (so the remaining checks evaluate against zero runs rather than
  raising).

### `scored_runs`

- SHALL pass iff the summary's `runs` is greater than `0`.
- Detail SHALL be `"{runs} scored repeat(s)"` when passing, else
  `"no artifact carried a usable headline score"`.

### `enough_repeats`

- SHALL pass iff `runs >= _effective_min_runs(min_runs)`.
- Detail SHALL be `"{runs} scored >= min_runs {required}"` when `runs > 0`, else
  `"need at least {required} scored repeat(s)"`.
- WHEN `min_runs` is non-positive THEN `required` is `0`, so any run count (including `0`)
  SHALL satisfy this check.

### `cv_defined`

- SHALL pass when the summary's `cv` is not `None`, **OR** when `stddev == 0` and `runs > 0` and
  `runs >= required` (identical runs are a defined zero-spread case).
- Detail SHALL be `"cv {cv}"` when `_is_number(cv)`, else the summary's `reason`, else
  `"coefficient of variation unavailable"`.

### `spread_acceptable`

- SHALL pass iff the summary's `stable` is truthy.
- Detail SHALL be `"cv {cv} <= max_cv {max_cv}"` when `_is_number(cv)` **and** the check passes;
  OTHERWISE the summary's `reason`, else `"spread not acceptable (cv {cv!r}, max_cv {max_cv})"`.

### Check-row sanitation (`_check_rows_list`)

- `None` SHALL yield `[]` silently; an empty list SHALL yield `[]` silently.
- WHEN `checks` is a non-list THEN it SHALL **emit a warning** and return `[]` (never coerced).
- A row SHALL be skipped **with a warning** when it is not a dict, is missing any
  `_CHECK_ROW_KEYS` key, has a non-`str` `name`, or has a `passed` whose `type(...) is not bool`
  (so a truthy `int` is rejected, and — unlike the newer sibling gates — a numpy scalar bool is
  **also** rejected here, since this module has no `_NUMPY_BOOL_TYPENAMES` allowance).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized row whose `passed` is falsy,
  over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `repeatability_gate_headline` SHALL be exactly:
  `repeatability gate: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `repeatability gate: STABLE ({runs} runs, cv {cv_txt})`, where `cv_txt` is `f"{cv:.1%}"` when
  `_is_number(cv)` else `n/a` (so a `None` cv renders `n/a`, and a `NaN` cv renders `nan%` —
  see the recorded divergence).
- OTHERWISE it SHALL be
  `repeatability gate: UNSTABLE ({f}/{n} checks failed: {names})`.

## Out of scope

- The spread metrics themselves (`benchmark/repeatability.py`).
- Adding the finiteness/`OverflowError` guard to `_is_number` (recorded above as a divergence;
  changing it would be a behavior change).

## Verification

- `tests/test_spec_064_repeatability_gate.py` exercises each EARS block above, including the
  recorded `_is_number` divergence (`NaN`/`inf`/oversized-int accepted, `Decimal` rejected), the
  non-list coercion, the non-positive `min_runs` floor, every check's pass/fail detail, **warning
  emission** for each warn branch, the numpy-bool rejection, and every headline branch.
- Broader coverage (including the CLI) remains in `tests/test_repeatability_gate.py`.
