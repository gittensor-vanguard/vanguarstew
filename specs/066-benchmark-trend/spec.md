# Spec 066 — benchmark score trend

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1889
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/regression.py`](../../benchmark/regression.py) (Spec 016 — inherits
  `headline_score` rather than re-implementing it),
  [`benchmark/promotion.py`](../../benchmark/promotion.py) (Spec 014 — mirrors the
  tuned-partition rule), [`benchmark/improvement.py`](../../benchmark/improvement.py),
  [`benchmark/gap_outlook.py`](../../benchmark/gap_outlook.py) (Spec 052 — headline score
  fallback), [`scripts/trend.py`](../../scripts/trend.py) (CLI)

This spec makes the **existing, implicit** trend contract explicit. It describes the as-built
behavior of `benchmark/trend.py`; it introduces **no behavior change**.

## Why

`benchmark/trend.py` is the shared headline-score extractor for the whole gate family:
`regression`, `improvement`, `gap_outlook`, `artifact_snapshot`, `repeatability` and
`leaderboard` all call `headline_score` instead of re-deriving it. Spec 016 says so explicitly
— *"The unscored-placeholder and tuned-partition rules live in `headline_score`; this gate
inherits them rather than re-implementing them"* — yet those rules have never been written
down, and a silent change to either moves all six gates at once. Specs
[018](../018-benchmark-score-calibration/spec.md), [019](../019-benchmark-comparability/spec.md)
and [027](../027-benchmark-gap-integrity/spec.md) each place `benchmark/trend.py` explicitly
under *Out of scope*, leaving the contract unwritten. This spec writes it down.

## User stories

1. **As a benchmark operator**, I can trend a headline composite across N saved artifacts and
   see point-to-point deltas, the overall change, and any regression.
2. **As a gate author** (`regression`, `improvement`, …), I can rely on a written
   `headline_score` contract instead of reading the implementation.
3. **As a reviewer**, every malformed-input and empty-series branch is written down
   (addressing the incompleteness class of rejection seen on Specs 057/059).

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_REGRESSION_THRESHOLD = 0.02` — a drop larger than this
  between consecutive scored points is reported as a regression.

### Numeric guard (`_is_number`)

- `_is_number(value)` SHALL be true only for non-boolean `int`/`float` values that are finite.
- A non-finite `float` (`NaN`/`Infinity`, which `json` round-trips verbatim) SHALL NOT be
  numeric, so a hand-edited or degenerate artifact cannot poison the trend.
- WHEN `value` is an `int` too large to convert to a `float` THEN `math.isfinite` raises
  `OverflowError` and `_is_number` SHALL return `False` (not propagate).

### Headline score extraction (`headline_score`)

- WHEN `artifact` is not a `dict` THEN `headline_score` SHALL return `None` (not raise).
- The score source SHALL be the `tuned` partition **only when `tuned` and `held_out` are
  *both* `dict`s**; otherwise the source SHALL be the top-level artifact. A `tuned` partition
  with a missing or non-`dict` `held_out` therefore SHALL fall through to the top level.
- WHEN the source's `scored_repos` is a number and falsey (`0`, `0.0`, `-0.0`) THEN the score
  SHALL be `None` (an aggregate that scored no repos reports a placeholder `composite_mean`,
  not a real score).
- Because `_is_number` excludes `bool`, a `scored_repos` of `False` SHALL NOT trigger the
  placeholder rule. A negative or string `scored_repos` is likewise not falsey-numeric and
  SHALL keep the score.
- WHEN the source's `composite_mean` passes `_is_number` THEN the score SHALL be
  `round(float(composite_mean), 3)`, otherwise `None`.
- A genuine `composite_mean` of `0.0` (with no zero `scored_repos`) SHALL be kept as `0.0`,
  not treated as unscored.

### Series and entry sanitation

- `_trend_series(series)` SHALL return `series` when it is a **`list`**, otherwise `[]`,
  warning on a non-`list` and staying **silent** on `None`. This is a `list` check, not a
  general iterable check: a `tuple` or generator of well-formed pairs is treated as empty (#528).
- `_trend_point(entry)` SHALL return the `(label, artifact)` pair when `entry` is a
  **2-element `list` or `tuple`**, otherwise `None` plus a warning rendering the offending
  entry with `%r`. A 1- or 3-element sequence, a bare scalar, `None`, a `dict`, a `set`, and a
  `str`/`bytes` of length 2 SHALL each be skipped — the last two are iterable and would
  otherwise unpack character-wise into a bogus pair.
- A skipped entry SHALL NOT abort the analysis: the well-formed points around it still count.

### Trend summary (`trend`)

Every summary SHALL include: `points`, `scored`, `total`, `first`, `last`, `change`, `min`,
`max`, `regressions`, `regression_threshold`.

- `points` SHALL carry one `{label, composite_mean, delta}` entry per **well-formed** entry,
  in input order. `total` SHALL be `len(points)`; `scored` SHALL count points with a numeric
  score.
- `delta` SHALL be the change from the previous **scored** point, and `None` for the first
  scored point and for any point whose own score is `None`. An unscored point therefore
  **bridges**: the next scored point's delta is measured against the last scored value, not
  against the gap.
- `first` / `last` SHALL be the first and last scored values; `change` SHALL be
  `_round(last - first)`; `min` / `max` SHALL be the range across scored values.
- `_round(value)` SHALL return `round(float(value), 3)` when `value` passes `_is_number`, and
  `None` otherwise. Because two finite scores can subtract to a non-finite result (`-1e308`
  and `1e308` overflow to `±inf`), both `delta` and `change` SHALL be `None` in that case
  **even though both points are scored** — the guard keeps an `inf` out of the summary rather
  than reporting it as a real movement.
- WHEN there are no scored points THEN `first`, `last`, `change`, `min` and `max` SHALL all be
  `None` and `regressions` SHALL be `[]`.
- WHEN there is exactly one scored point THEN `change` SHALL be `0.0` (not `None`), since the
  first and last scored values are the same point.
- `regressions` SHALL list consecutive **scored** pairs whose drop exceeds
  `regression_threshold`, each `{from_label, to_label, drop}` with `drop` positive.
- The drop SHALL be `round(from_score - to_score, 3)` **before** the comparison, so
  floating-point noise cannot tip a drop equal to the threshold over it
  (`0.60 - 0.58 == 0.02000…018`).
- The comparison SHALL be strict (`drop > regression_threshold`): a drop **exactly equal** to
  the threshold is NOT a regression.
- `regression_threshold` SHALL be echoed back verbatim and is **not validated**: a non-numeric
  threshold raises `TypeError` from the comparison once two scored points exist, and surfaces
  no error below that. `scripts/trend.py` constrains `--threshold` to a `float` via `argparse`
  and also catches `TypeError` at the call site, so the CLI cannot reach this path.

### Trend headline (`trend_headline`)

- WHEN `summary` is not a `dict`, or its `scored` is missing/falsey THEN the headline SHALL be
  exactly `trend: no scored artifacts`.
- `_trend_regressions(regressions)` SHALL return the value when it is a `list`, otherwise `[]`
  (warning on a non-`list`, silent on `None`), so a malformed summary still renders a count.
- The arrow SHALL be `up` when `change > 0`, `down` when `change < 0`, and `flat` when
  `change == 0` **or when `change` is non-numeric**.
- `change` SHALL render as `{change:+.3f}` when numeric, otherwise `n/a`.
- The headline SHALL be:
  `trend: {first} -> {last} ({arrow} {change_txt}) over {scored} scored point(s); {n} regression(s)`.

### Pure analysis

- The module SHALL perform no I/O.
- `trend()` SHALL NOT mutate its inputs, and SHALL NOT copy the artifacts it reads (the caller's
  nested partition objects keep their identity).

## Out of scope

- Whether a single run clears a floor (`benchmark/regression.py`, Spec 016;
  `benchmark/improvement.py`) or a two-artifact diff (`scripts/compare_eval.py`).
- Changing the placeholder / tuned-partition semantics that six sibling gates inherit.
- Repairing the `trend()` docstring's "iterable" wording (see Verification) — a product change.

## Verification

- `tests/test_spec_066_trend.py` exercises each EARS block above, including the non-`list`
  series container, malformed entries, the unscored-bridge delta, threshold exclusivity, the
  single-point `change`, every headline branch, and non-mutation.
- Broader coverage (including the CLI) remains in `tests/test_trend.py`.
- **Recorded, not transcribed:** `trend()`'s docstring says *"``series`` is an iterable of
  ``(label, artifact)`` pairs"*, but `_trend_series` requires a `list` — a `tuple` or generator
  of well-formed pairs yields an empty summary. This spec documents the **shipped** `list`
  behavior and notes the discrepancy rather than restating the docstring.
