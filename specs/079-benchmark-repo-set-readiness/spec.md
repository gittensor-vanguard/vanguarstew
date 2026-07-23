# Spec 079 — Repo-set acceptance-readiness gate

**Module:** `benchmark/repo_set_readiness.py`
**Status:** Accepted (characterization)
**Tests:** `tests/test_spec_079_repo_set_readiness.py`
**Issue:** #1939

## Purpose

`validate_repo_set` answers whether a repo-set config is *well-formed*. It does not answer the
orthogonal question this module owns: is a well-formed set actually **adequate** to run M3/M4
generalization acceptance on? Starting a long `run_eval --generalization` replay only to discover
the set has a single tuned repo, no held-out repos, an LLM-era freeze window, or a leftover
starter placeholder wastes the run.

`check_readiness(config)` gates that up front. It delegates well-formedness to the canonical
validator, then reports a fixed sequence of named readiness checks, and the companion
`scripts/repo_set_readiness.py` exits non-zero when the set is not ready. This spec pins the check
set, the ordering, the thresholds, the human summary, and the malformed-input degradation so the
readiness bar is a reviewed contract rather than an implicit one.

## Dependencies (contract stated so this gate is fully defined)

- **`benchmark.repo_set.validate_repo_set(config)`** returns a validated `RepoSet` (with
  `.entries`, `.tuned()`, `.held_out()`, each entry carrying `.name`, `.source`, `.freeze_window`)
  or raises `RepoSetError` when the config is malformed. `check_readiness` catches that and reports
  it as a failed `valid_config` check; it never propagates the exception.
- **`benchmark.repo_set.is_placeholder_source(source)`** is `True` when `source` is a shipped
  starter `OWNER/…` placeholder URL. It backs the `no_placeholder_sources` check.

## Definitions

- **Readiness checks (in order):** `valid_config`, `min_tuned`, `min_held_out`, `pre_llm_windows`,
  `no_placeholder_sources`.
- **Thresholds:** `DEFAULT_MIN_TUNED = 2`, `DEFAULT_MIN_HELD_OUT = 1`, overridable per call.
- **Pre-LLM cutoff:** `PRE_LLM_CUTOFF = "2021-01-01"`. A repo is *late* — and fails
  `pre_llm_windows` — when its `freeze_window.before` is absent, non-string, or lexicographically
  greater than the cutoff. (A post-cutoff or unbounded window samples the LLM-assisted era, whose
  "next maintainer action" ground truth may itself be LLM-written — circular.)
- **Usable check row:** a `dict` with a non-blank `str` `name` and a `bool` `passed`. The
  `failed_checks` / `readiness_headline` helpers read only usable rows.

## Acceptance criteria (EARS)

- **AC-1 — Ready path.** When a config is well-formed and meets every threshold with only pre-LLM
  windows and no placeholder sources, `check_readiness` SHALL return `passed: True` with `checks`
  named exactly `[valid_config, min_tuned, min_held_out, pre_llm_windows, no_placeholder_sources]`
  in that order, and SHALL report `repos_total`, `repos_tuned`, `repos_held_out`.
- **AC-2 — Invalid config short-circuits.** When `validate_repo_set` rejects the config (or the
  config is not a `dict`), `check_readiness` SHALL return `passed: False` with `checks` containing
  only a failed `valid_config`, and SHALL NOT raise.
- **AC-3 — Minimum tuned.** When fewer than `min_tuned` tuned (non-held-out) repos are present,
  the `min_tuned` check SHALL fail.
- **AC-4 — Minimum held-out.** When fewer than `min_held_out` held-out repos are present, the
  `min_held_out` check SHALL fail.
- **AC-5 — Pre-LLM windows.** When any repo's freeze window is unbounded or bounded on/after
  `PRE_LLM_CUTOFF`, the `pre_llm_windows` check SHALL fail and name the offending repo(s).
- **AC-6 — No placeholder sources.** When any repo `source` is a starter placeholder, the
  `no_placeholder_sources` check SHALL fail and name the offending repo(s).
- **AC-7 — Configurable thresholds.** `min_tuned` and `min_held_out` SHALL be overridable per
  call and change the pass/fail outcome accordingly.
- **AC-8 — Headline.** `readiness_headline` SHALL summarize a passing result as
  `"readiness: READY (<tuned> tuned, <held-out> held-out)"` and a failing one as
  `"readiness: NOT READY (<f>/<n> checks failed: <names>)"`; a non-dict result SHALL yield
  `"readiness: invalid result"` and a result with no usable checks
  `"readiness: no checks evaluated"`.
- **AC-9 — Malformed result tolerance.** `failed_checks` SHALL return `["result"]` for a non-dict
  result, `[]` for a non-list `checks` container, and SHALL skip rows that are not usable — never
  raising `KeyError`. `_check_rows_list` SHALL treat `None`/`[]` silently, warn-and-empty a
  non-list (including a tuple), and skip non-dict rows, rows missing a required key, blank names,
  and non-`bool` `passed` values.

## Non-goals

- Pure evaluation: no I/O, never mutates the config.
- It does not define well-formedness (`validate_repo_set` owns that) nor the placeholder URL set
  (`is_placeholder_source` owns that); it composes them into a readiness verdict.
