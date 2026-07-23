# Spec 074 — repeatability assessment

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1922
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repeatability.py`](../../benchmark/repeatability.py) (the assessment under
  test — `assess_repeatability`, distinct from the `repeatability_gate` wrapper),
  [`benchmark/trend.py`](../../benchmark/trend.py) (`headline_score`, the per-run score source),
  [`benchmark/run_clean.py`](../../benchmark/run_clean.py) (`check_run_clean`, the per-repeat error
  scan, Spec 073), [`scripts/repeatability.py`](../../scripts/repeatability.py) (the CI entry point)

This spec makes the **existing, implicit** repeatability-assessment contract explicit. It describes
the as-built behavior of `benchmark/repeatability.py`; it introduces **no behavior change**. This is
the assessment (`assess_repeatability`), not the CLI gate wrapper.

## Why

`run_replay` is deterministic given a fixed seed, but a real acceptance run varies with
model/inference noise across repeats. `trend` tracks a score over *successive* runs to catch a
regression; `assess_repeatability` measures the **spread of several *repeated* runs of the same
config** — is the benchmark reproducible enough to trust a single number (ROADMAP M1: "re-runs are
stable")? It reports mean/stddev/min/max/range and the coefficient of variation, and calls the set
stable when the CV clears a threshold with enough scored repeats.

## User stories

1. **As a CI maintainer**, I can gate reproducibility on `scripts/repeatability.py` and log a stable
   `repeatability_headline()` STABLE/UNSTABLE line.
2. **As a benchmark operator**, I can trust a stable verdict means enough scored, clean repeats with
   a low run-to-run coefficient of variation.
3. **As a reviewer**, every not-clean / no-score / insufficient-runs / zero-mean / malformed-input
   branch is written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MAX_CV` SHALL be `0.05`, `DEFAULT_MIN_RUNS` SHALL be `2`.

## Acceptance criteria (EARS)

### Helpers

- `_round(value)` SHALL return `round(float(value), 3)` for a non-boolean `int`/`float`, else `None`.
- `_coerce_runs(value)` SHALL return `value` when it is a non-boolean `int` and `>= 0`; a non-int /
  bool / negative value SHALL yield `None` (with a warning for a non-`None`, non-int value).
- `_effective_min_runs(min_runs)` SHALL return `DEFAULT_MIN_RUNS` when `min_runs` is not a non-bool
  `int`, else `max(0, min_runs)`.
- `_repeat_not_clean_detail(artifact)` SHALL return `None` when `artifact` is not a dict or
  `check_run_clean` passes; otherwise a short reason string — the first `findings` entry, else the
  first failing check's `detail`, else `"recorded errors"`.
- `_repeatability_artifacts(artifacts)` SHALL return `artifacts` when it is a list, else `[]` (with
  a warning for a non-`None` non-list).

### Assessment (`assess_repeatability`)

- The result SHALL always carry `stable`, `runs`, `scores`, `mean`, `stddev`, `cv`, `min`, `max`,
  `range`, `max_cv`, `min_runs`, `reason`.
- WHEN any repeat is not clean (`_repeat_not_clean_detail` is not `None`) THEN it SHALL return early
  with `reason = "repeat {i} not clean: {detail}"` (1-based index) and `stable = False`.
- `scores` SHALL be each artifact's non-`None` `headline_score`; `runs` SHALL be `len(scores)`.
- WHEN `runs == 0` THEN `reason` SHALL be `"no scored runs"`.
- WHEN `runs < _effective_min_runs(min_runs)` THEN `reason` SHALL be
  `"insufficient runs: {runs} scored < min_runs {required}"`.
- OTHERWISE `mean` SHALL be `round(mean(scores), 3)`; `stddev` SHALL be `round(stdev(scores), 3)`
  when more than one score, else `0.0` (the sample/Bessel-corrected stddev).
- `cv` SHALL be `0.0` when `stddev == 0`; `None` when `stddev != 0` and `mean == 0` (a spread that
  can't be normalized); otherwise `round(stddev / abs(mean), 3)`.
- `min`/`max` SHALL be the score extremes; `range` SHALL be `_round(max - min)`.
- WHEN `cv is None` THEN `reason` SHALL be
  `"coefficient of variation undefined (zero mean with nonzero spread)"`; WHEN `cv > max_cv` THEN
  `reason` SHALL be `"cv {cv} exceeds max_cv {max_cv}"`; OTHERWISE `stable` SHALL be `True`.

### Headline (`repeatability_headline`)

- WHEN `result` is not a dict, or `_coerce_runs(result["runs"])` is `None`/`0` THEN it SHALL be
  `repeatability: no scored runs`.
- WHEN `runs < _effective_min_runs(result["min_runs"])` THEN it SHALL be
  `repeatability: inconclusive ({runs} run(s))`.
- OTHERWISE it SHALL be `repeatability: {STABLE|UNSTABLE} over {runs} runs (mean {mean}, cv {cv})`,
  where the verdict is `STABLE` when `result["stable"]` is truthy, and `cv` is rendered `{:.1%}` when
  a non-bool number else `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `assess_repeatability()` SHALL NOT mutate its inputs; a non-list `artifacts`, and an artifact with
  no usable score, SHALL be handled (skipped) rather than raise.

## Out of scope

- `headline_score` (`trend`) and `check_run_clean` (`run_clean`, Spec 073) internals, and the
  CLI-gate wrapper.
- Tuning the default thresholds.

## Verification

- `tests/test_spec_074_repeatability.py` exercises each EARS block above, pinning **literal**
  expected values, using score sets whose mean/stddev/cv are exact under `round(..., 3)` (e.g.
  `[0.60, 0.62, 0.64]` → mean `0.62`, stddev `0.02`) so assertions are stable across platforms.
- Broader coverage (including the CLI) remains in `tests/test_repeatability.py`.
