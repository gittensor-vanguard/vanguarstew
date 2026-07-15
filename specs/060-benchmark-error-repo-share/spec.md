# Spec 060 — error repo share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1695
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repo_score_spread.py`](../../benchmark/repo_score_spread.py) (per-repo score spread),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/run_clean.py`](../../benchmark/run_clean.py) (partition error scanning)

This spec makes the **existing, implicit** error-repo-share contract explicit. It describes the
as-built behavior of `benchmark/error_repo_share.py`; it introduces **no behavior change**.

## Why

A multi-repo run's headline can be computed over only the repos that survived clone/freeze.
This read-only utility reports the fraction of countable repos that carry a truthy `error`,
with per-partition detail for generalization artifacts.

## User stories

1. **As a benchmark operator**, I can see what share of repos failed before trusting a headline.
2. **As a CI maintainer**, I can log a stable `error_repo_share_headline()` string.
3. **As a reviewer**, every malformed-input and empty-slice branch is written down (addressing
   the incompleteness class of rejection seen on Specs 057/059).

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_error_repo_share(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_int(value)` SHALL be true only for built-in `int` values that are not `bool`.
- `_is_number(value)` SHALL be true only for non-boolean `int`/`float` values.

### Error detection (`_has_error`)

- WHEN `entry` is not a `dict` THEN `_has_error` SHALL return `False`.
- WHEN `entry` is a `dict` THEN `_has_error` SHALL return `bool(entry.get("error"))`
  (so `None`, `""`, missing key → clean; any truthy message → errored).

### Per-repo flags (`_repo_error_flags`)

- WHEN `per_repo` is a `list` THEN:
  - each **dict** entry SHALL contribute `_has_error(entry)`;
  - each **non-empty stripped string** entry SHALL contribute `True` (malformed/corrupt row);
  - `None`, ints, empty/whitespace strings, and other non-dict/non-string values SHALL be
    **skipped** (not counted);
  - WHEN `per_repo` is a list the top-level slice `error` SHALL **not** be counted
    (no double-count with `per_repo`).
- OTHERWISE (no list `per_repo`) the slice SHALL contribute exactly one flag:
  `_has_error(slice_)`.
- WHEN `per_repo` is an **empty list** THEN the flag list SHALL be `[]`.

### Share helper (`_error_share`)

- WHEN `flags` is empty THEN `_error_share` SHALL return
  `{"repos": 0, "error_repos": 0, "error_share": None}`.
- OTHERWISE `error_share` SHALL be `round(error_repos / repos, 3)`.

### Error repo share summary (`summarize_error_repo_share`)

Every summary SHALL include: `kind`, `repos`, `error_repos`, `error_share`, `partitions`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- WHEN `kind` is `generalization` THEN the top-level share SHALL combine tuned and held-out
  flags, and `partitions` SHALL be
  `{"tuned": _error_share(...), "held_out": _error_share(...)}`.
- OTHERWISE the top-level share SHALL come from `_repo_error_flags(artifact)` and
  `partitions` SHALL be `None`.
- An `invalid` artifact (including a coerced non-dict → `{}`) SHALL set `partitions` to
  `None`. Because the single-repo path still contributes one flag for a dict without a
  `per_repo` list, an empty/`invalid` object WITHOUT `per_repo: []` SHALL report
  `repos: 1`, `error_repos: 0`, `error_share: 0.0` (one clean synthetic row). A multi-shaped
  empty list (`{"per_repo": []}`) SHALL report `repos: 0` and `error_share: None`.

### Error repo share headline

- WHEN `repos` is missing, not an int, or `0` THEN the headline SHALL be exactly:
  `error repo share: no repos`.
- OTHERWISE WHEN `error_share` passes `_is_number` THEN it SHALL format as `{share:.1%}`,
  else `n/a`, and the headline SHALL be:
  `error repo share: {share_txt} ({error_repos}/{repos} repos errored)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_error_repo_share()` SHALL NOT mutate its input dict.

## Out of scope

- Whether a run is *clean enough* to gate on (`benchmark/run_clean.py`).
- Changing acceptance / partition-error scanning semantics.

## Verification

- `tests/test_spec_060_error_repo_share.py` exercises each EARS block above, including
  malformed `per_repo` rows, empty slices, missing keys, and headline `n/a`.
- Broader coverage (including CLI) remains in `tests/test_error_repo_share.py`.
