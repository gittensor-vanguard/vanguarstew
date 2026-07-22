# Spec 075 — repo-set readiness gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1939
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repo_set.py`](../../benchmark/repo_set.py) (the canonical
  `validate_repo_set` / `is_placeholder_source` this gate reuses, Spec 005),
  [`scripts/repo_set_readiness.py`](../../scripts/repo_set_readiness.py) (CLI wrapper),
  [`benchmark/component_floor.py`](../../benchmark/component_floor.py) (sibling gate)

This spec makes the **existing, implicit** repo-set readiness contract explicit. It describes the
as-built behavior of `benchmark/repo_set_readiness.py`; it introduces **no behavior change**.

## Why

`validate_repo_set` (Spec 005) answers "is this config *well-formed*?" — but nothing documented the
orthogonal gate: is a well-formed set actually **adequate** to start an M3/M4 generalization
acceptance run? Starting a long `run_eval --generalization` replay only to discover the set has one
tuned repo, an LLM-era freeze window, or a leftover starter placeholder wastes the whole run. The
gate has evolved through several merged hardening rounds (#712 checks-row sanitation, the
`both_tiers` → `pre_llm_windows` replacement, #1698 CLI error reporting) without an SDD contract,
unlike its sibling gates (Specs 059–062, 071). Making the contract explicit pins the check order,
the per-check detail strings, and the exact `pre_llm_windows` boundary so a silent regression (or a
quietly reintroduced `recent`-window repo) is caught by contract tests.

## User stories

1. **As a benchmark operator**, I can gate an acceptance run on `check_readiness(config)` and read
   named, ordered checks explaining exactly why a set is not ready.
2. **As a CI maintainer**, I can log a stable `readiness_headline()` string alongside the JSON
   result and fail the pipeline via the strict CLI.
3. **As a reviewer**, malformed-input handling, threshold semantics, and every headline branch are
   written down.

## Acceptance criteria (EARS)

### Gate evaluation and check order

- `check_readiness(config, min_tuned=DEFAULT_MIN_TUNED, min_held_out=DEFAULT_MIN_HELD_OUT)` SHALL
  evaluate named checks in this fixed order:
  `valid_config`, `min_tuned`, `min_held_out`, `pre_llm_windows`, `no_placeholder_sources`.
- `DEFAULT_MIN_TUNED` SHALL be `2`; `DEFAULT_MIN_HELD_OUT` SHALL be `1`;
  `PRE_LLM_CUTOFF` SHALL be `"2021-01-01"`.
- Every check row SHALL be `{"name": str, "passed": bool, "detail": str}` with `passed` coerced via
  `bool()`.

### Validity gate (`valid_config`)

- WHEN `config` is not a `dict` THEN the result SHALL contain exactly one check, `valid_config`,
  failed, with detail `config must be a JSON object, got {type_name}` — and SHALL NOT raise.
- WHEN `validate_repo_set(config)` raises `RepoSetError` THEN the result SHALL contain exactly one
  check, `valid_config`, failed, with the stringified error as detail.
- WHEN the config validates THEN `valid_config` SHALL pass with detail
  `valid repo set ({n} repo(s))` and the remaining four checks SHALL be evaluated.

### Adequacy thresholds (`min_tuned`, `min_held_out`)

- `min_tuned` SHALL pass iff the count of tuned (non-held-out) repos is `>= min_tuned`, with detail
  `{n} tuned repo(s) >= min_tuned {min_tuned}` (the same detail string on pass and fail).
- `min_held_out` SHALL pass iff the count of held-out repos is `>= min_held_out`, with detail
  `{n} held-out repo(s) >= min_held_out {min_held_out}`.
- Both thresholds SHALL be caller-configurable keyword arguments.

### Pre-LLM freeze windows (`pre_llm_windows`)

- A repo SHALL fail the window invariant when its `freeze_window.before` is missing or not a `str`
  (an unbounded window samples LLM-era history), or when `before > PRE_LLM_CUTOFF` under string
  comparison.
- A `before` exactly equal to `PRE_LLM_CUTOFF` SHALL pass (the comparison is strictly greater).
- WHEN offending repos exist THEN `pre_llm_windows` SHALL fail with the **sorted** repo names in
  the detail `repo(s) sampling LLM-era history (no/late ``before`` bound): {names}`; OTHERWISE it
  SHALL pass with detail `all freeze windows bounded before 2021-01-01`.

### Placeholder guard (`no_placeholder_sources`)

- `no_placeholder_sources` SHALL fail iff any entry's `source` matches
  `benchmark.repo_set.is_placeholder_source`, listing the offending repo names comma-joined in the
  detail `placeholder source(s): {names}`; OTHERWISE it SHALL pass with detail
  `no starter placeholder sources`.

### Result shape

- Every result SHALL carry `passed` (the conjunction of all check rows), `checks`, and the echoed
  `min_tuned` / `min_held_out` thresholds.
- WHEN the config validated THEN the result SHALL additionally carry `repos_total`, `repos_tuned`,
  and `repos_held_out` counts; WHEN it did not, those keys SHALL be absent.

### Failed checks (`failed_checks`)

- WHEN `result` is not a `dict` THEN `failed_checks(result)` SHALL return `["result"]`.
- OTHERWISE it SHALL return the `name` of every sanitized check row whose `passed` is falsy
  (a row missing `passed` counts as failed), in check order.

### Checks-row sanitation (`_check_rows_list`)

- `None` SHALL yield `[]` silently (absent key); an empty list SHALL yield `[]` silently.
- A non-list container (including tuples and other iterables) SHALL yield `[]` after logging a
  warning — never coerced.
- Non-dict rows SHALL be skipped with a warning; WHEN a non-empty `checks` produces zero usable
  rows THEN an additional warning SHALL be logged.

### Readiness headline

- WHEN `result` is not a `dict` THEN the headline SHALL be exactly `readiness: invalid result`.
- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be exactly `readiness: no checks evaluated`.
- WHEN `result["passed"]` is truthy THEN the headline SHALL be
  `readiness: READY ({repos_tuned} tuned, {repos_held_out} held-out)`, substituting `?` for either
  count when its key is absent.
- OTHERWISE the headline SHALL be
  `readiness: NOT READY ({failed}/{total} checks failed: {names})` with the failed check names
  comma-joined in check order.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_readiness()` SHALL NOT mutate its input config.

## Out of scope

- Well-formedness validation itself (`validate_repo_set`, Spec 005) — reused, not redefined.
- The CLI wrapper `scripts/repo_set_readiness.py` (strict exit codes, #1698 clean load errors) —
  covered by `tests/test_repo_set_readiness.py`.
- The retired `both_tiers` check (replaced by `pre_llm_windows`; rationale recorded in the module
  docstring).

## Verification

- `tests/test_spec_075_repo_set_readiness.py` exercises each EARS block above: the fixed check
  order and constants, both `valid_config` short-circuit arms (non-dict / `RepoSetError`),
  threshold boundary and configurability, the `pre_llm_windows` equal-to-cutoff boundary plus the
  missing- and late-`before` arms with sorted names, the placeholder guard, result-shape key
  presence/absence, `failed_checks` semantics, checks-row sanitation (with warnings), every
  headline branch pinned as **literal** strings (including the `?` fallbacks), and no-mutation
  purity.
- Broader coverage (shipped JSON sets, the CLI, #1698 error paths) remains in
  `tests/test_repo_set_readiness.py`.
