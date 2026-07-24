# Spec 082 — Markdown report-rendering contract

**Module:** `benchmark/report.py`
**Status:** Accepted (characterization)
**Tests:** `tests/test_spec_082_report.py`
**Issue:** #1995 (behaviours also pinned: #616, #507, #667)

## Purpose

`render_report` turns a saved `run_eval --out` JSON artifact into readable Markdown — the
human-facing view of every benchmark result, and the renderer behind `scripts/report.py`. It is
pure formatting: no I/O, it never mutates its input, and it tolerates missing or malformed fields
by rendering `n/a` rather than raising, so even a partial or error artifact still produces a
report.

This spec pins the shape dispatch, the per-shape headline/lines, the generalization verdict, and —
most importantly — the "`n/a` over a crash or a fabricated number" degradations, so the report
contract is reviewed rather than implicit.

## Definitions

- **Artifact shapes.** `render_report` classifies an artifact and dispatches to one of five
  renderers, in this precedence:
  1. non-`dict` → **unknown**;
  2. generalization (`generalization_gap` present, `repo_set` a `str`, both `tuned` and
     `held_out` partition-like dicts, and no top-level `composite_mean`) → **generalization**;
  3. `error` present *and* no `composite_mean` → **error**;
  4. multi-repo (`repos` ≥ 1 and `scored_repos` numeric and `composite_mean` present, and no
     scalar `tasks`) → **multi-repo**;
  5. `composite_mean` present → **single-repo**;
  6. `error` present → **error**;
  7. otherwise → **unknown**.
- **Numeric.** `_is_number` accepts only a **finite, non-boolean** `int`/`float`; `NaN`,
  `Infinity`, `bool`, and an oversized int that overflows `float()` are non-numeric.
- **Unscored partition.** `scored_repos == 0` marks a placeholder `composite_mean` of `0.0`
  (nothing was actually scored), not a real score.
- **Gap verdict.** On a generalization report, a `generalization_gap` greater than the inspect
  threshold (default `DEFAULT_GAP_INSPECT_THRESHOLD = 0.10`, overridable via
  `gap_inspect_threshold`) yields `inspect`, otherwise `pass`; a non-numeric gap yields `n/a`.

## Acceptance criteria (EARS)

- **AC-1 — Single-repo.** When an artifact carries a `composite_mean` and is not multi-repo or
  generalization, `render_report` SHALL emit `# Benchmark report (single-repo)` with composite,
  judge, and objective means, the judge W-L-T and disagreement rate, and the task count.
- **AC-2 — Multi-repo.** When an artifact is a `run_multi_replay` aggregate, `render_report` SHALL
  emit `# Benchmark report (multi-repo)` with a `- Repos: <scored>/<total> scored` tally and, when
  present, a `### Per-repo` table.
- **AC-3 — Generalization.** When an artifact has a `generalization_gap`, a `str` `repo_set`, and
  `tuned`/`held_out` partitions, `render_report` SHALL emit `# Benchmark report (generalization)`
  with the gap, the verdict, and a rendered `Tuned` and `Held-out` partition.
- **AC-4 — Error.** When an artifact carries an `error` and no `composite_mean`, `render_report`
  SHALL emit `# Benchmark report (error)`.
- **AC-5 — Unknown.** When an artifact is not a `dict`, or is an unrecognized shape,
  `render_report` SHALL emit `# Benchmark report (unknown)` without raising.
- **AC-6 — Dispatch precedence.** When a scored artifact also carries a stray `error` field, the
  `composite_mean` (scored) branch SHALL win over the error branch.
- **AC-7 — Verdict threshold.** The generalization verdict SHALL be `inspect` when the gap exceeds
  the threshold and `pass` otherwise, and the threshold SHALL be overridable per call.
- **AC-8 — Non-finite → n/a (#616).** When a numeric field is `NaN`, `Infinity`, or an oversized
  int, `render_report` SHALL render `n/a` for it rather than crashing or emitting a bogus number.
- **AC-9 — Unscored → n/a (#507).** When a partition reports `scored_repos == 0`, its composite,
  judge, objective, and foresight lines SHALL render `n/a`, not the placeholder `0.0`.
- **AC-10 — Malformed containers → n/a + warn (#667).** When `per_repo` is a non-list, or
  `composite_parts`/`foresight`/`judge_report` is the wrong type, `render_report` SHALL degrade to
  `n/a`/no-table with a `logging.WARNING`, never selecting a wrong template or raising.
- **AC-11 — Purity.** `render_report` SHALL NOT mutate its input artifact and SHALL always return
  a newline-terminated `str`.

## Non-goals

- No I/O; the CLI wrapper (`scripts/report.py`) owns file reading and error exit codes.
- It does not compute scores, gaps, or foresight axes — it formats what an artifact already
  carries.
