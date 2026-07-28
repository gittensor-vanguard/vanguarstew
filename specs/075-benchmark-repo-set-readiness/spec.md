# Spec 075 — repo-set readiness gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1939
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/repo_set_readiness.py`](../../benchmark/repo_set_readiness.py) (the gate
  under test), [`benchmark/repo_set.py`](../../benchmark/repo_set.py) (`validate_repo_set` /
  `is_placeholder_source`, contracted separately by [Spec 005](../005-repo-set/spec.md)),
  [`scripts/repo_set_readiness.py`](../../scripts/repo_set_readiness.py) (the CLI entry point)

This spec makes the **existing, implicit** repo-set readiness contract explicit. It describes the
as-built behavior of `benchmark/repo_set_readiness.py`; it introduces **no behavior change**.

## Why

`validate_repo_set` (Spec 005) checks that a repo-set config is *well-formed*, but nothing checks
the orthogonal question: is a well-formed set actually **adequate** to run M3/M4 generalization
acceptance on? Starting a long `run_eval --generalization` replay only to discover the set has one
tuned repo, or a leftover starter placeholder, wastes the run. `check_readiness` turns that question
into a reproducible pass/fail gate with four named checks, reusing `validate_repo_set` so a
malformed config fails a single `valid_config` check rather than raising.

## User stories

1. **As a benchmark operator**, I can gate a repo-set config on `scripts/repo_set_readiness.py
   --strict` before starting a generalization run, and trust a `readiness: READY (...)` headline.
2. **As a curator**, I can trust `pre_llm_windows` catches any repo whose freeze window samples the
   LLM-assisted era (no `before` bound, or one at/after the cutoff) — the invariant that replaced
   the retired `both_tiers` check on 2026-07-16.
3. **As a reviewer**, every non-dict / malformed-row / boundary / multi-failure branch is written
   down, addressing the incompleteness class of rejection this exact issue drew on its first two
   attempts (PR #1940: missing-`freeze_window` and non-dict `type(...).__name__` derivation
   under-specified, no multi-failure-headline or negative-threshold coverage).

## Constants

- `DEFAULT_MIN_TUNED` SHALL be `2`, `DEFAULT_MIN_HELD_OUT` SHALL be `1`.
- `PRE_LLM_CUTOFF` SHALL be `"2021-01-01"`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Config validation (`valid_config`)

- WHEN `config` is not a `dict` (`None`, a `list`, a `str`, an `int`, a `float`, or a `bool` — `bool`
  is not a `dict` instance despite JSON's boolean/object distinction) THEN a single `valid_config`
  check SHALL fail with detail `f"config must be a JSON object, got {type(config).__name__}"`,
  using the literal runtime type name (`NoneType`, `list`, `str`, `int`, `float`, `bool`), and
  `checks` SHALL contain exactly that one entry — no `min_tuned`/`min_held_out`/`pre_llm_windows`/
  `no_placeholder_sources` check SHALL be added.
- WHEN `config` is a `dict` but `validate_repo_set(config)` raises `RepoSetError` THEN
  `valid_config` SHALL fail with the exception's `str(...)` verbatim as detail, and `checks` SHALL
  again short-circuit to that one entry.
- WHEN `validate_repo_set` succeeds THEN `valid_config` SHALL pass with detail
  `f"valid repo set ({n} repo(s))"` (`n = len(repo_set)`), and the remaining four checks SHALL run,
  in this fixed order: `min_tuned`, `min_held_out`, `pre_llm_windows`, `no_placeholder_sources`.

### `min_tuned` / `min_held_out`

- `min_tuned` SHALL pass iff `len(repo_set.tuned()) >= min_tuned`; detail SHALL always be
  `f"{n_tuned} tuned repo(s) >= min_tuned {min_tuned}"`, pass or fail.
- `min_held_out` SHALL pass iff `len(repo_set.held_out()) >= min_held_out`; detail SHALL always be
  `f"{n_held_out} held-out repo(s) >= min_held_out {min_held_out}"`.
- A threshold of `0` or negative SHALL always pass (a repo-set holds at least one repo per Spec
  005's non-empty-`repos` rule, and a count is never negative).
- Both thresholds SHALL be caller-configurable via `check_readiness(config, min_tuned=,
  min_held_out=)`, defaulting to `DEFAULT_MIN_TUNED`/`DEFAULT_MIN_HELD_OUT`, and SHALL be echoed
  back verbatim on the result's `min_tuned`/`min_held_out` keys regardless of the outcome.

### `pre_llm_windows`

- A repo entry SHALL be "late" (fails the repo-set) when its `freeze_window["before"]` is not a
  `str` — covering a `freeze_window` absent from the raw config entirely (defaults to `{}` via
  `RepoEntry`'s field default and `validate_repo_set`'s own default), an explicit empty
  `freeze_window: {}`, and a `freeze_window` present but lacking a `before` key — **or** is a `str`
  that sorts (ISO-8601 lexicographic) strictly greater than `PRE_LLM_CUTOFF`.
- A `before` **equal to** `PRE_LLM_CUTOFF` ("2021-01-01") SHALL NOT be late — the boundary is a
  strict `>`, so a window bounded exactly at the cutoff passes.
- The check SHALL pass iff no entry is late. Late entry names SHALL be alphabetically sorted in the
  failure detail: `f"repo(s) sampling LLM-era history (no/late \`before\` bound): {late}"` (the
  literal `list` repr); the pass detail SHALL be
  `f"all freeze windows bounded before {PRE_LLM_CUTOFF}"`.

### `no_placeholder_sources`

- SHALL fail when any entry's `source` is a starter placeholder per `is_placeholder_source`
  (starts with `https://github.com/OWNER/`); failing entry names SHALL be collected in repo-set
  entry order (not sorted) and comma-joined: `f"placeholder source(s): {', '.join(placeholders)}"`.
- Pass detail SHALL be `"no starter placeholder sources"`.

### Result shape (`_result`)

- The result SHALL always carry `passed` (`all(check["passed"] for check in checks)`), `checks`,
  `min_tuned`, `min_held_out`.
- On the `valid_config`-failure short circuit, the result SHALL carry **only** those four keys — no
  `repos_total`/`repos_tuned`/`repos_held_out`.
- On the success path, the result SHALL additionally carry `repos_total` (`len(repo_set)`),
  `repos_tuned`, `repos_held_out`.

### `failed_checks`

- A non-`dict` `result` SHALL return `["result"]`.
- A `dict` `result` SHALL return the `name` of every sanitized row (via `_check_rows_list`) whose
  `passed` is falsy, in `checks` order.

### `readiness_headline`

- A non-`dict` `result` SHALL return `"readiness: invalid result"`.
- WHEN sanitized `checks` is empty (missing key, `None`, empty list, a non-list container, or a
  list with no usable row) THEN it SHALL return `"readiness: no checks evaluated"`.
- WHEN `result["passed"]` is truthy THEN it SHALL return
  `f"readiness: READY ({result.get('repos_tuned', '?')} tuned, "
  f"{result.get('repos_held_out', '?')} held-out)"` — the `'?'` fallback fires on a hand-built
  `result` dict that omits `repos_tuned`/`repos_held_out` (never on a `check_readiness` output,
  where the success path always sets both).
- OTHERWISE it SHALL return
  `f"readiness: NOT READY ({len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"`, where
  `failed` lists **every** failing check's name (not just the first), in `checks` order.

### Checks-row sanitation (`_check_rows_list`)

- `None` and non-list `checks` (including a `tuple`, `range`, or scalar) SHALL yield `[]`, with a
  warning logged only for the non-list case (a `None` `checks` — the common "key absent" case — is
  silent).
- A row SHALL be skipped, with a warning, when it is not a `dict`; is missing `name` and/or
  `passed`; has a non-`str` or blank/whitespace-only `name`; or a non-`bool` `passed`.
- WHEN `checks` is non-empty but no row survives sanitation THEN an additional summary warning
  SHALL be logged.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_readiness()` SHALL NOT mutate its `config` argument, even on the invalid/malformed paths.

## Out of scope

- `validate_repo_set`'s own field-level validation rules (Spec 005).
- `scripts/repo_set_readiness.py`'s CLI argument parsing and `load_config` error handling (#1698) —
  already covered by `tests/test_repo_set_readiness.py`'s CLI subprocess tests.
- Tuning the default thresholds or `PRE_LLM_CUTOFF`.

## Verification

- `tests/test_spec_075_repo_set_readiness.py` exercises every EARS block above with literal
  expected check names, `passed` values, and detail strings, including the non-dict-config
  type-name matrix, the missing/empty/absent-`before` `freeze_window` arms, the strict `>` cutoff
  boundary, negative thresholds, and a deliberate multi-check-failure case whose headline lists
  every failed name. Broader coverage (the shipped `curated.json`/`example.json` fixtures, the CLI)
  stays in `tests/test_repo_set_readiness.py`.
