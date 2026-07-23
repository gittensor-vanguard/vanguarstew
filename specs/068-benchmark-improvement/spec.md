# Spec 068 — improvement (adoption) gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1900
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/improvement.py`](../../benchmark/improvement.py) (the gate under
  test), [`benchmark/regression.py`](../../benchmark/regression.py) (the opposite gate — blocks
  a drop), [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (provides
  `_partition_error`), [`benchmark/trend.py`](../../benchmark/trend.py) (provides
  `headline_score`), [`scripts/improvement.py`](../../scripts/improvement.py) (the CI entry
  point)

This spec makes the **existing, implicit** improvement-gate contract explicit. It describes the
as-built behavior of `benchmark/improvement.py`; it introduces **no behavior change**.

> **Numbering note:** `specs/068-benchmark-disagree-order-share` also carries number 068 (its
> issue assigned the number independently). Duplicate spec numbers with distinct topic slugs are
> established practice in this tree (042 offline-share / tie-order-share, 046, 047, 048).

## Why

`regression` blocks a candidate that *drops* below a baseline; `check_improvement` is the
opposite, an **adoption** decision: accept a candidate as the new best only when it beats the
baseline's headline composite by at least `min_gain`, and only when **both** runs completed
clean. `scripts/improvement.py` exits non-zero when the candidate did not improve enough, so
each check's pass condition, detail string and the ADOPT/HOLD headline are a CI contract worth
pinning.

## User stories

1. **As a CI maintainer**, I can gate adoption on `scripts/improvement.py` and know from stable
   detail strings exactly why a candidate was held.
2. **As a benchmark operator**, I can trust ADOPT means both artifacts scored, neither's
   evaluated partition recorded any error (top-level **or** per-repo), and the gain cleared the
   margin.
3. **As a reviewer**, the score-source and error-scan semantics this gate borrows
   (`_headline_source`, `_partition_error`, `headline_score`) are written down here rather than
   left implicit — including the lone-`tuned` arm, the per-repo scan and the non-finite cases
   (addressing the closure findings on the first attempt at this spec, which left
   `_headline_source`-without-`held_out` and `_partition_error` unspecified and the headline
   format incomplete).

## Constants

- `DEFAULT_MIN_GAIN` SHALL be `0.02`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Numeric helpers

- `_is_number(value)` SHALL be true only for a non-boolean `int`/`float` that is finite:
  `NaN`, `inf`, `-inf` SHALL be false, and an oversized `int` (`10**400`, where `math.isfinite`
  raises `OverflowError`) SHALL yield false, never raise. `Decimal`, `str`, `None`, containers
  and both `bool` values SHALL be false.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_num(value)` SHALL render `f"{value:.3f}"` when `_is_number(value)` (so `0.1` renders
  `0.100`), else exactly `"n/a"` — hence `None`, `True`, `NaN`, `inf`, `-inf` and an oversized
  `int` all render `n/a`.

### Score and cleanliness sources

- `_headline_source(artifact)` SHALL return the `tuned` partition when **both** `tuned` and
  `held_out` are dicts, otherwise the artifact itself. WHEN `held_out` is missing or a non-dict
  THEN a lone `tuned` dict SHALL NOT be treated as the headline — the artifact is evaluated at
  the **top level** (mirroring `benchmark.trend.headline_score`).
- Scores SHALL come from `benchmark.trend.headline_score`: the evaluated partition's
  `composite_mean` rounded to 3 places, or `None` when the artifact is a non-dict, the field is
  missing / non-numeric / non-finite / oversized, or the partition carries a zero
  `scored_repos` (an aggregate that scored no repos reports a placeholder `0.0`, treated as
  unscored).
- `_artifact_error(artifact)` SHALL return the first error found, or `None` when clean:
  the artifact's own top-level `error` first, else
  `acceptance._partition_error(_headline_source(artifact))`, which scans **three** places:
  1. the evaluated partition's `error` — a whole-partition failure;
  2. every `per_repo[i]` dict row's `error` — a repo that failed to clone/freeze is recorded
     in-row without setting the top-level `error`;
  3. a `per_repo[i]` entry that is itself a non-empty string — a malformed row, failed closed
     (the raw string is the error value).
- A **falsy** `error` (empty string, `None`, `0`) SHALL be treated as clean at every scan site.
- Non-dict, non-string `per_repo` entries and a non-list `per_repo` SHALL be ignored; a
  non-dict artifact SHALL yield `None` (no error) — its missing score fails the gate instead.
- WHEN the artifact is a generalization report THEN a failed `held_out` partition SHALL be
  intentionally **not** scanned — only the evaluated (`tuned`) partition's cleanliness gates
  adoption.

### Gate (`check_improvement`)

- The result SHALL always carry `passed`, `checks`, `baseline_composite`,
  `candidate_composite`, `gain`, `min_gain`; `passed` SHALL be
  `all(c["passed"] for c in checks)`; every check row SHALL carry `name`, `passed` (a native
  `bool`) and `detail`.
- `baseline_composite` / `candidate_composite` SHALL echo the two `headline_score` values
  (`None` when unscored); `min_gain` SHALL echo the argument **unvalidated** (see below).
- Exactly two checks SHALL be emitted in order: `both_scored`, `improves_by_margin`.
- `both_scored` SHALL pass iff both scores are non-`None` **and** both `_artifact_error`s are
  `None`. Its detail SHALL be, in priority order:
  1. WHEN it passes: `"baseline composite {_num(base)}, candidate composite {_num(cand)}"`;
  2. WHEN the baseline errored: `"baseline error: {err!r}"` — the baseline is named even when
     the candidate **also** errored;
  3. WHEN only the candidate errored: `"candidate error: {err!r}"`;
  4. OTHERWISE (a score missing): `"a composite score is missing from one artifact"`. (The
     module carries a defensive duplicate `else` arm with the same message; it is unreachable
     as-built and left undisturbed by this documentation-only spec.)
- `gain` SHALL be `round(candidate_composite - baseline_composite, 3)` when `both_scored`, else
  `None`.
- `improves_by_margin` SHALL pass iff `gain is not None and gain >= min_gain`. Detail SHALL be
  `"gain {_num(gain)} >= {min_gain}"` whenever `gain` is not `None` — **including on failure**
  (e.g. `"gain 0.010 >= 0.02"` with `passed` false, and a **negative** gain renders e.g.
  `"gain -0.200 >= 0.02"`) — else `"cannot compare composites"`.
- `min_gain` SHALL participate **raw** in both the comparison and the detail interpolation
  (`0.02` renders `0.02`, not `0.020`): a `NaN` `min_gain` fails every comparison (detail
  `"gain 0.200 >= nan"`), a `-inf` `min_gain` passes any defined gain. This asymmetry with the
  `_num`-formatted `gain` is as-built and pinned.

### Check-row sanitation (`_check_rows_list`)

- `None` SHALL yield `[]` silently; an empty list SHALL yield `[]` silently.
- WHEN `checks` is a non-list THEN it SHALL **emit a warning** and return `[]` (never coerced).
- A row SHALL be skipped **with a warning** when it is not a dict, is missing any
  `_CHECK_ROW_KEYS` key, has a non-`str` `name`, or a non-`bool` `passed`
  (`isinstance(row["passed"], bool)`) — so an `int` `1` and a numpy scalar bool are rejected,
  while an **empty-`str` `name` survives** (only `isinstance(name, str)` is required, unlike
  `judge_gate` / `run_clean`; tolerable because sanitation feeds only the presentation-layer
  helpers, and every row `check_improvement` itself emits is well-formed).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.
- All warnings SHALL be emitted on the `benchmark.improvement` logger.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized row whose `passed` is
  falsy, over `_dict(result).get("checks")` — a non-dict `result` SHALL yield `[]`.
- WHEN no sanitized check rows exist (a non-dict result, a missing / non-list / empty `checks`,
  or rows that all fail sanitation) THEN `improvement_headline` SHALL be exactly
  `improvement: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `improvement: ADOPT (composite {_num(baseline_composite)} -> {_num(candidate_composite)},
  gain {_num(gain)})` — so a hand-built passing result with missing fields renders
  `improvement: ADOPT (composite n/a -> n/a, gain n/a)`.
- OTHERWISE it SHALL be `improvement: HOLD ({f}/{n} checks failed: {names})`, where both `f`
  and `n` count **sanitized** rows only (a malformed row is excluded from both counts).

### Pure evaluation

- The module SHALL perform no I/O.
- `check_improvement()` SHALL NOT mutate its inputs, and `None` / non-dict / malformed
  artifacts SHALL fail the relevant checks rather than raise.

## Out of scope

- The regression gate (`benchmark/regression.py`) and the promotion decision.
- The internals of `headline_score` / `_partition_error` beyond the behavior consumed here
  (their own specs/tests own them).
- Removing the unreachable defensive `else` arm, validating `min_gain`, or tuning
  `DEFAULT_MIN_GAIN` (each would be a behavior change).
- The CLI exit-code mapping (`scripts/improvement.py`), covered by
  `tests/test_improvement.py`.

## Verification

- `tests/test_spec_068_improvement.py` exercises each EARS block above with **literal**
  expected strings, including: the lone-`tuned`-without-`held_out` arm, all three
  `_partition_error` scan sites plus the ignored `held_out` failure and the falsy-error skip,
  the zero-`scored_repos` placeholder, non-finite and oversized composites, the **negative
  gain** and `None`-artifact cases, the raw `min_gain` asymmetry (`NaN` / `-inf` arms), every
  `both_scored` detail-priority branch (including both-errored precedence), every headline
  branch (`ADOPT`, the `n/a` triple, `HOLD` counts over sanitized rows only, `no checks
  evaluated`), warning **emission** for each sanitation warn branch, and the empty-name
  acceptance / `int`-and-numpy-bool rejection. All pinned values have a platform-stable `repr`.
- Broader coverage (including the CLI) remains in `tests/test_improvement.py`.
