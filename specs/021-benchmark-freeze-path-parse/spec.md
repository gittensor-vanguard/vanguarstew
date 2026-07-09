# Spec 021 — NUL-delimited git path parsing (`parse_path_list`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #838
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (freeze/scrub pipeline),
  [`benchmark/taskgen.py`](../../benchmark/taskgen.py) (`revealed_window` consumer)

This spec makes the **existing, implicit** path-list parsing contract explicit. It describes the
as-built behavior of `benchmark/freeze.py::parse_path_list`; it introduces **no behavior change**.
Git `-z` output feeds objective scoring via changed-file paths — so NUL splitting rules must be
written down and verified.

## Why

Whitespace-splitting corrupts paths that contain spaces or shell-sensitive characters, silently
depressing module-recall scores. `parse_path_list` is the single parser for NUL-delimited git
path lists; making its contract explicit lets reviewers check freeze/taskgen changes against intent.

## User stories

1. **As a benchmark maintainer**, I know git `-z` path output is split on NUL bytes only — so
   filenames with spaces survive intact.
2. **As a reviewer**, empty-field dropping and empty-input behavior are written down — so parser
   changes are checked against the spec.

## Acceptance criteria (EARS)

### Input type

- `parse_path_list(out)` SHALL accept a `str` git `-z` path-list payload.
- WHEN `out` is the empty string `""` THEN the function SHALL return `[]` (not raise).

### NUL splitting

- The function SHALL split `out` on NUL bytes (`"\0"`), **not** on whitespace or newlines.
- WHEN a path contains spaces, semicolons, dollar signs, or other shell-sensitive characters
  THEN the returned list SHALL preserve the path as a single element.

### Empty-field dropping

- Leading, trailing, and duplicate NUL separators SHALL produce empty fields that are **dropped**
  from the result.
- WHEN `out` is `"\0a\0\0b\0"` THEN the result SHALL be `["a", "b"]`.

### Output shape

- The function SHALL return a `list[str]`.
- Every returned element SHALL be a non-empty string (no `""` entries).
- The function SHALL NOT mutate its input string.

### Pure evaluation

- The function SHALL perform no I/O and SHALL NOT depend on global state.

## Out of scope

- `git archive` / `export_tree` error handling — separate freeze concerns.
- `revealed_window` commit selection — `benchmark/taskgen.py`.
- Changing split semantics — code changes follow the SDD loop in their own PRs.

## Verification

- `tests/test_spec_021_freeze_path_parse.py` (this PR) exercises each EARS block above.
- Broader freeze and taskgen coverage remains in `tests/test_freeze.py` and `tests/test_taskgen.py`.
