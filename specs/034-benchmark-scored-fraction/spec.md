# Spec 034 — scored fraction summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #960
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/sample_adequacy.py`](../../benchmark/sample_adequacy.py) (task-count gates)

This spec makes the **existing, implicit** scored-fraction contract explicit. It describes the
as-built behavior of `benchmark/scored_fraction.py`; it introduces **no behavior change**. A
multi-repo headline `composite_mean` can look healthy when only a handful of repos were scored —
that coverage signal must be written down and verified.

## Why

`run_multi_replay` reports `repos` and `scored_repos`, but nothing summarizes how completely a run
scored its repository set. `summarize_scored_fraction()` is the reproducible read-only summary for
CI dashboards; making its contract explicit lets reviewers check scored-fraction changes against
intent.

## User stories

1. **As a benchmark operator**, I can read `scored_repos / repos` before trusting a multi-repo or
   generalization headline mean.
2. **As a CI maintainer**, I can log a stable `scored_fraction_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_scored_fraction(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer (avoids truthy counts).
- `float` values — including whole-number floats such as `5.0` — SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline fraction
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Scored fraction (`_scored_fraction`)

- WHEN both `repos` and `scored` pass `_is_int` AND `repos > 0` AND `0 <= scored <= repos` THEN
  `_scored_fraction(repos, scored)` SHALL return `round(scored / repos, 3)` (a finite value in
  `[0.0, 1.0]`).
- WHEN `repos <= 0` THEN `_scored_fraction` SHALL return `None`.
- WHEN `scored < 0` THEN `_scored_fraction` SHALL return `None`.
- WHEN `scored > repos` THEN `_scored_fraction` SHALL return `None`.
- WHEN either argument fails `_is_int` THEN `_scored_fraction` SHALL return `None`.
- WHEN `scored == 0` and `repos > 0` THEN `_scored_fraction` SHALL return `0.0` (distinct from
  `None` for incoherent counts).

### Slice fraction (`_slice_fraction`)

- SHALL read `repos` and `scored_repos` from the slice dict (missing keys treated as `None`).
- The optional `skipped` field SHALL NOT influence the fraction (a bogus or missing `skipped`
  never suppresses a fraction that `repos`/`scored_repos` can define).
- WHEN `_scored_fraction` returns a number THEN the slice SHALL return
  `{"repos": repos, "scored_repos": scored, "scored_fraction": fraction}` with the original int
  counts.
- WHEN `_scored_fraction` returns `None` THEN the slice SHALL return
  `{"repos": repos_or_none, "scored_repos": scored_or_none, "scored_fraction": None}` where each
  count field echoes the raw value when it passes `_is_int`, otherwise `None`.

### Combined fraction (`_combined`)

- WHEN every input slice has `_is_int` values for both `repos` and `scored_repos` THEN `_combined`
  SHALL sum counts across slices and set `scored_fraction` via `_scored_fraction` on the totals.
- WHEN any slice lacks `_is_int` values for either count THEN `_combined` SHALL return
  `{"repos": None, "scored_repos": None, "scored_fraction": None}`.

### Artifact-kind branches (`summarize_scored_fraction`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL always include these keys (never omitted):

| Key | Always present | Value when unavailable |
| --- | --- | --- |
| `kind` | yes | `artifact_kind` result (`"invalid"` for empty/non-classifiable input) |
| `repos` | yes | `None` when counts incoherent or missing |
| `scored_repos` | yes | `None` when counts incoherent or missing |
| `scored_fraction` | yes | `None` when fraction cannot be computed |
| `partitions` | yes | `None` for non-generalization kinds; dict for `generalization` |

1. **`single` or `multi`** — top-level counts come from `_slice_fraction(artifact)`;
   `partitions` SHALL be `None`.
2. **`generalization`** — SHALL report per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]` (each via `_slice_fraction` on that partition), plus overall counts
   from `_combined(tuned, held_out)` at the top level. Overall `scored_fraction` SHALL be `None`
   unless both partitions carry coherent `_is_int` counts (even when one partition's fraction is
   `None` due to `scored > repos`).
3. **`invalid`** — SHALL return `kind == "invalid"` with `repos`, `scored_repos`, and
   `scored_fraction` all `None`, and `partitions` `None`.

### Scored fraction headline

`scored_fraction_headline(summary)` SHALL return a one-line human summary.

- WHEN the input is not a `dict` THEN it SHALL be coerced via `_dict` (same as missing keys).
- Let `fraction_txt` be `f"{fraction:.1%}"` when `scored_fraction` passes `_is_number`, otherwise
  the literal string `n/a` (lowercase, no quotes).
- WHEN both `scored_repos` and `repos` pass `_is_int` THEN the headline SHALL be exactly:
  `scored fraction: {fraction_txt} ({scored_repos}/{repos} repos scored)` — note the space after
  the colon, the parentheses around the count clause, and the literal suffix ` repos scored`.
- OTHERWISE the headline SHALL be exactly: `scored fraction: {fraction_txt}` with no count clause.

Exact examples (character-for-character):

| Condition | Expected headline |
| --- | --- |
| `scored_fraction=0.8`, `scored_repos=4`, `repos=5` | `scored fraction: 80.0% (4/5 repos scored)` |
| `scored_fraction=0.0`, `scored_repos=0`, `repos=5` | `scored fraction: 0.0% (0/5 repos scored)` |
| `scored_fraction=1.0`, `scored_repos=4`, `repos=4` | `scored fraction: 100.0% (4/4 repos scored)` |
| `scored_fraction=None` (missing or incoherent) | `scored fraction: n/a` |
| `scored_fraction=0.8`, `repos=None`, `scored_repos=4` | `scored fraction: 80.0%` |
| `scored_fraction=float("nan")`, counts present | `scored fraction: n/a (4/5 repos scored)` |

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_scored_fraction()` SHALL NOT mutate its input dict.

## Out of scope

- Task-level sample adequacy gates (`benchmark/sample_adequacy.py`).
- Per-repo error shares (`benchmark/error_repo_share.py`).
- Changing `run_replay` / `run_multi_replay` repo accounting semantics.

## Verification

- `tests/test_spec_034_scored_fraction.py` (this PR) exercises each EARS block above.
- Broader integration and CLI coverage remains in `tests/test_scored_fraction.py`.
