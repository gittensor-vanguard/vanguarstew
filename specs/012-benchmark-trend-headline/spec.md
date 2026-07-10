# Spec 012 — benchmark score trend & regression gating

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #761
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/trend.py`](../../benchmark/trend.py) (this module),
  [`scripts/trend.py`](../../scripts/trend.py) (CLI),
  [`specs/016-benchmark-regression/spec.md`](../016-benchmark-regression/spec.md) (single-run gate),
  [`specs/014-benchmark-promotion/spec.md`](../014-benchmark-promotion/spec.md)

This spec makes the **existing, implicit** trend contract explicit. It describes the as-built
behavior of `benchmark/trend.py` (`headline_score`, `trend`, `trend_headline`); it introduces
**no behavior change**.

## Why

`compare_eval` diffs *two* artifacts and `--fail-under` gates a *single* run against a fixed floor.
Neither catches a score that slides gradually across a *series* of runs. `trend` adds the N-way
view: given several replay artifacts in chronological order, it extracts each one's headline
composite score, reports the point-to-point deltas and the overall change, and flags **regressions**
— a drop from one point to the next larger than a threshold — so CI can gate on a slow slide, not
only a single dip below a static floor.

The module is **pure analysis**: no I/O, never mutates its inputs, and tolerant of a degenerate
artifact. A missing, non-numeric, or non-finite (NaN/±Inf) score, or an aggregate run that scored
no repos (`scored_repos: 0`, whose `composite_mean` is a placeholder `0.0`), contributes `None` and
is skipped in the delta/regression math rather than poisoning the trend or raising.

## User stories

1. **As a benchmark operator**, I can see how the headline score moved across a chronological series
   of runs, with per-point deltas and the overall change.
2. **As a CI maintainer**, I can gate on regressions (a drop beyond a configurable threshold) and
   render a stable one-line headline.
3. **As a reviewer**, the handling of unscored / non-finite / malformed points, the placeholder
   `scored_repos: 0` `0.0`, and the exact delta / regression / first-last semantics are written down.

## Acceptance criteria (EARS)

### Number validity (`_is_number`)

- `_is_number(value)` SHALL return `True` only for a **finite** `int` or `float` that is **not** a
  `bool`. It SHALL return `False` for `bool`, `str`, `None`, other non-numeric types, and for `NaN`,
  `+Inf`, `-Inf`.
- WHEN `value` is an `int` too large to convert to `float` (so `math.isfinite` raises
  `OverflowError`, e.g. `10**400`) THEN `_is_number` SHALL return `False`, never raise.

### Headline score (`headline_score`)

The single comparable score for one artifact. Every result SHALL be a `float` rounded to 3 decimals,
or `None`.

- WHEN `artifact` is not a `dict` THEN the headline SHALL be `None`.
- A **single-** or **multi-repo** artifact's headline SHALL be its **top-level** `composite_mean`.
- WHEN both `tuned` and `held_out` are `dict`s (a `--generalization` artifact) THEN the headline
  SHALL be the **tuned** partition's `composite_mean` (the primary figure).
- WHEN the source (top level, or the tuned partition) reports a numeric `scored_repos` equal to `0`
  — an aggregate run that scored no repos and carries a **placeholder** `composite_mean` of `0.0` —
  THEN the headline SHALL be `None` (unscored), never the placeholder `0.0`.
- WHEN `composite_mean` is missing, non-numeric, or non-finite (`NaN`/`±Inf`) THEN the headline
  SHALL be `None`.
- A **genuine** `0.0` on an artifact with **no** `scored_repos` key (e.g. a single-repo artifact)
  SHALL be preserved as `0.0`, distinct from the unscored `None` above.
- The returned score SHALL be `round(float(composite_mean), 3)`.

### Series coercion (`_trend_series`, `_trend_point`)

- WHEN `series` is a `list` THEN it SHALL be used as-is.
- WHEN `series` is `None` THEN it SHALL be treated as empty with **no** warning.
- WHEN `series` is a non-`None`, non-`list` value THEN it SHALL be treated as empty and a warning
  naming its type SHALL be logged (a malformed series must not abort analysis).
- A valid series **entry** SHALL be a 2-element `list` or `tuple` `(label, artifact)`. Any other
  entry — a bare scalar, `None`, a `str`, `bytes`, an empty / 1-element / 3-element sequence, a
  `dict`, or a custom object — SHALL be skipped with a warning naming the offending value (`%r`),
  without aborting the analysis; the well-formed points around it still count. In particular a
  2-character `str` (`"ab"`) SHALL NOT be unpacked character-wise into a bogus `(label, artifact)`.

### Trend summary (`trend`)

Every result SHALL include exactly the keys: `points`, `scored`, `total`, `first`, `last`, `change`,
`min`, `max`, `regressions`, `regression_threshold`.

- `points` SHALL be one `{label, composite_mean, delta}` object per surviving entry, in input order.
  `composite_mean` SHALL be `headline_score(artifact)` (`None` when unscored). `delta` SHALL be the
  rounded change from the **previous scored** point, and SHALL be `None` for the first scored point
  and for any point whose own score is `None`.
- `scored` SHALL be the number of points carrying a usable score; `total` SHALL be the number of
  surviving points.
- `first` / `last` SHALL be the first and last **scored** values (skipping any leading/trailing
  unscored points); `change` SHALL be `round(last - first, 3)`; `min` / `max` SHALL be the range
  across scored values. WHEN no point is scored THEN all five SHALL be `None`.
- `regressions` SHALL list each consecutive pair of **scored** points whose `drop` (computed as
  `round(from - to, 3)`) **strictly exceeds** `regression_threshold`, as `{from_label, to_label,
  drop}` with `drop` positive. A drop **exactly equal** to the threshold SHALL NOT be a regression.
- `regression_threshold` SHALL echo the argument unchanged (default `0.02`,
  `DEFAULT_REGRESSION_THRESHOLD`).
- Unscored and non-finite points SHALL be skipped in the delta and regression math — they **bridge**
  the surrounding scored points (a `0.60 → (skip) → 0.50` is still a `0.10` drop) — rather than
  contributing a `None`/`NaN` delta or a spurious regression.
- WHEN `series` is a non-`list`, is empty, or every entry is malformed THEN `trend` SHALL return the
  empty summary (`points: []`, `scored: 0`, `total: 0`, `first`/`last`/`change`/`min`/`max`: `None`,
  `regressions: []`).

### Trend headline (`trend_headline`)

- WHEN `summary` is not a `dict`, or has no scored points (`scored` falsy) THEN the headline SHALL be
  exactly `trend: no scored artifacts`.
- OTHERWISE the headline SHALL read
  `trend: {first} -> {last} ({arrow} {change}) over {scored} scored point(s); {n} regression(s)`,
  where `arrow` is `up` when `change > 0`, `down` when `change < 0`, and `flat` otherwise; `change`
  is formatted `{:+.3f}` when numeric and `n/a` when not (in which case `arrow` is `flat`); and `n`
  is the number of regressions.
- WHEN `summary.regressions` is a non-`list` THEN it SHALL be treated as zero regressions
  (`_trend_regressions`), with a warning for a non-`None`, non-`list` value.

### Pure evaluation

- The module SHALL perform **no I/O** — a call to `headline_score`, `trend`, or `trend_headline`
  SHALL touch neither the filesystem nor the network.
- `trend()` SHALL **NOT mutate** its `series` argument or any artifact within it, for well-formed
  **and** every degenerate shape (non-`list` series, malformed entries, unscored / non-finite /
  placeholder artifacts). The contract is verified by deep-copying each input before the call and
  asserting the input is unchanged afterward (a value-equality, not a shallow-identity, check).

## Verification

- `tests/test_spec_012_trend_headline.py` exercises each EARS block above, including the
  single/multi/generalization headline paths, the `scored_repos: 0` placeholder vs a genuine `0.0`,
  series/entry coercion, the delta/regression/first-last summary semantics, the headline branches,
  and the deep non-mutation / no-I/O purity checks.
- Broader coverage (including the CLI) remains in `tests/test_trend.py`.
