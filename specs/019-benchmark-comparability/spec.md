# Spec 019 — the cross-artifact comparability gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #819
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/005-repo-set`](../005-repo-set/spec.md) (repo-set curation),
  [`benchmark/leaderboard.py`](../../benchmark/leaderboard.py) (ranking consumer)

This spec makes the **existing, implicit** comparability contract explicit. It describes the
as-built behavior of `benchmark/comparability.py`; it introduces **no behavior change**.
Leaderboard and diff tooling need artifacts on the same benchmark surface — so kind classification,
repo-set matching, and gate headlines must be written down and verified.

## Why

Comparing headline scores across artifacts only makes sense when they cover the same repos and
artifact shape. A multi-repo run over `{a,b,c}` must not be ranked against one over `{a,b,d}`.
Making that contract explicit lets reviewers check comparability changes against intent.

## User stories

1. **As a benchmark operator**, I can verify two or more saved artifacts are comparable before
   ranking or diffing them — so misleading tables are caught early.
2. **As a CI maintainer**, I can gate leaderboard steps on `check_comparability()` with a stable
   pass/fail headline — so non-comparable sets fail closed.
3. **As a reviewer**, artifact-kind rules and malformed-input handling are written down — so a
   change to `comparability.py` is checked against the spec.

## Acceptance criteria (EARS)

### Artifact kind classification

- `artifact_kind(artifact)` SHALL classify replay artifacts as one of:
  `single`, `multi`, `generalization`, or `invalid`.
- WHEN an artifact has both `tuned` and `held_out` dict partitions and a `generalization_gap`
  field THEN the kind SHALL be `generalization`.
- WHEN an artifact has a `per_repo` field THEN the kind SHALL be `multi`.
- WHEN an artifact is a non-empty dict without those multi/generalization markers THEN the kind
  SHALL be `single`.
- IF the artifact is not a dict or is empty THEN the kind SHALL be `invalid`.

### Repo identity extraction

- `_repo_key(entry)` SHALL derive a stable string identity from, in order: `repo_path`, `url`,
  `repo`, `name`, then a 10-character `freeze_commit` prefix, else a fallback from entry keys.
- WHEN a `per_repo` container is not a list THEN repo-key extraction SHALL log a warning and
  treat the container as empty (not raise).
- WHEN a `per_repo` row is not a dict THEN that row SHALL be skipped (not raise).

### Comparability checks

- `check_comparability(artifacts)` SHALL evaluate named checks and return
  `{"passed", "checks", "artifact_kind", "repo_sets"}`.
- `passed` SHALL be `True` only when every check passes.
- The gate SHALL always report these checks:
  1. `enough_artifacts` — at least two JSON-object artifacts were supplied;
  2. `same_artifact_kind` — every artifact shares the same non-`invalid` kind;
  3. `same_repo_set` — for `multi` artifacts, every `per_repo` list names the same repos; for
     `generalization`, separate `tuned_same_repo_set` and `held_out_same_repo_set` checks apply;
     for `single` artifacts, repo-set comparison is not applicable but the check SHALL pass when
     kinds match.
- WHEN multi-repo repo sets differ or are empty after malformed-row skipping THEN
  `same_repo_set` (or partition-specific checks) SHALL fail.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and log
  a warning (not raise).
- WHEN a check row is not a dict, or is missing `name`/`passed`, or has non-string `name`, or has
  non-bool `passed` THEN that row SHALL be skipped with a warning.
- `failed_checks(result)` SHALL return only check names from usable rows with `"passed": false`.
- WHEN `checks` is missing, empty, or contains only unusable rows THEN `failed_checks()` SHALL
  return `[]`.

### Comparability headline

- `comparability_headline(result)` SHALL return a one-line human summary.
- IF `checks` is empty after sanitization THEN the headline SHALL read
  `comparability: no checks evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `COMPARABLE` and the artifact
  kind.
- WHEN `result["passed"]` is false THEN the headline SHALL include `NOT COMPARABLE` and the
  names of failed checks (when available).
- Malformed `checks` fields SHALL NOT crash headline formatting.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_comparability()` SHALL NOT mutate its input list or artifact dicts.

## Out of scope

- Headline score extraction or trend comparison (`benchmark/trend.py`).
- Changing leaderboard rendering (`benchmark/leaderboard.py`).
- Repo-set config loading (`benchmark/repo_set.py`).

## Verification

- `tests/test_spec_019_comparability.py` (this PR) exercises each EARS block above.
- Broader CLI coverage remains in `tests/test_comparability.py`.
