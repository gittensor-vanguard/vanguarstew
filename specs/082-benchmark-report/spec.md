# Spec 082 — Benchmark report rendering contract

**Module:** `benchmark/report.py`
**Status:** Accepted (characterization)
**Tests:** `tests/test_spec_082_report.py`
**Issue:** #1995

## Purpose

`render_report` turns a saved `run_eval --out` artifact (added in #471 / #452) into the Markdown
that every human reading a benchmark result actually sees — the gate and summary modules already
have EARS specs under `specs/`, but the renderer that presents their output has never had one.
This spec documents its existing behaviour and pins it with characterization tests; it proposes
no change to `report.py` or `scripts/report.py`.

## Definitions

- **Shape.** `render_report` classifies its input `artifact` into exactly one of five shapes and
  dispatches to a dedicated renderer:
  - **generalization** — carries `generalization_gap`, a string `repo_set`, and both `tuned` and
    `held_out` as partition-shaped dicts (`_is_generalization`);
  - **error** — has a truthy `error` field and no `composite_mean`;
  - **multi-repo** — an aggregate `run_multi_replay` artifact: no `tasks` field, a numeric
    `repos` >= 1, a numeric `scored_repos`, and `composite_mean` present (`_is_multi_repo`);
  - **single-repo** — carries `composite_mean` and did not match multi-repo or generalization;
  - **unknown** — a non-`dict` input, or a `dict` matching none of the above.

  The dispatch in `render_report` checks generalization, then error, then multi-repo, then
  single-repo, then falls back to error (for a truthy `error` alongside an unrecognized shape) and
  finally unknown — a fixed precedence, and no input shape raises.
- **Numeric (`_is_number`).** A value is numeric only if it is a non-`bool` `int`/`float` and
  `math.isfinite` accepts it (an oversized int that overflows `float()` counts as non-numeric, not
  an exception). Every score, count, and rate field is read through this guard.
- **Unscored partition.** A partition (top-level artifact or a `tuned`/`held_out` sub-dict) whose
  `scored_repos` is present and numerically zero is *unscored*: its composite/judge/objective
  means and foresight axes render `n/a` rather than the placeholder `0.0` the aggregator wrote.
- **`n/a` degradation.** Any field that is missing, wrong-typed, or non-numeric renders the literal
  string `n/a` (or `n=0` for a foresight sample count) instead of raising or fabricating a value.
  A non-`list` (or entry-malformed) `per_repo` degrades to no table, logging a `WARNING` naming
  the offending type — never a wrong template.
- **Purity.** `render_report` performs no I/O and never mutates the `artifact` it is given.

## Acceptance criteria (EARS)

- **AC-1 — Shape dispatch precedence.** When given a `dict` artifact, `render_report` SHALL pick
  generalization over error over multi-repo over single-repo, and SHALL render the `unknown`
  template for a non-`dict` input or a `dict` matching none of the recognized shapes, without
  raising for any input.
- **AC-2 — Scored-with-stray-error still renders scored.** When an artifact carries both
  `composite_mean` and a truthy `error`, `render_report` SHALL render it as its scored shape
  (single- or multi-repo), not the error template — `composite_mean` presence outranks a stray
  `error` field.
- **AC-3 — Generalization verdict.** For a generalization artifact, `render_report` SHALL report
  `inspect` when `generalization_gap` exceeds `gap_inspect_threshold` (default
  `DEFAULT_GAP_INSPECT_THRESHOLD`, aliasing `PROMOTION_MAX_GAP` from
  `benchmark/generalization_policy.py`, overridable per call) and `pass` otherwise, and SHALL
  report `n/a` (never `inspect`/`pass`) when the gap is missing or non-finite.
- **AC-4 — Non-finite or oversized numeric fields render `n/a`.** A `NaN`, `Infinity`, or an int
  too large for `float()` to represent, in any scored field (composite/judge/objective means,
  rates, counts, the generalization gap), SHALL render `n/a` rather than crash or a fabricated
  number (#616).
- **AC-5 — Unscored partition renders `n/a`, not `0.0`.** When a partition's `scored_repos` is
  present and zero, `render_report` SHALL render its composite/judge/objective means and every
  foresight axis as `n/a`, even though the aggregator wrote a placeholder `composite_mean: 0.0`
  (#507).
- **AC-6 — Malformed `per_repo` degrades to no table, with a warning.** When `per_repo` (top-level
  or within a partition) is present but not a `list`, or every entry is unusable, `render_report`
  SHALL omit the per-repo table (never rendering a row of `n/a` placeholders) and SHALL emit a
  `logging.WARNING` naming the offending type; an absent or empty `per_repo` SHALL omit the table
  silently, with no warning.
- **AC-7 — Malformed `composite_parts`/`foresight`/`judge_report` degrade to `n/a`, with a
  warning where applicable.** A non-`dict` `composite_parts` or `foresight` SHALL degrade every
  field it would have supplied to `n/a`/`n=0` and SHALL emit a `logging.WARNING` naming the
  offending type; a non-`dict` `judge_report`, or one missing `wins`/`losses`/`ties`, SHALL render
  `Judge W-L-T: n/a` without a warning (its absence is an ordinary unscored/legacy case, not a
  malformed container).
- **AC-8 — Purity.** `render_report` SHALL perform no file or network I/O and SHALL NOT mutate the
  `artifact` argument, for any of the five shapes.

## Non-goals

- No behaviour change to `report.py` or `scripts/report.py` — this spec characterizes the shipped
  renderer.
- It does not define `run_eval`, `run_multi_replay`, or the scoring/foresight computations
  themselves — it only documents how their output is displayed.
