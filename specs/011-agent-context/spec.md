# Spec 011 — agent knowable-at-T context

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #2007
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Leakage integrity / Agent contract*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/github_context.py`](../../benchmark/github_context.py) (the
  benchmark-side producer, Spec 081 in flight), [`benchmark/leakage.py`](../../benchmark/leakage.py)
  (the frozen-path scrubber this module mirrors, Specs 003/022),
  [`benchmark/freeze.py`](../../benchmark/freeze.py) (imports `README_PROBE_NAMES`; sibling
  git-only builder), [`tests/test_scrubber_alignment.py`](../../tests/test_scrubber_alignment.py)
  (guards the cross-module scrubber alignment), Specs 006/007/009/010 (the other agent modules)

This spec makes the **existing, implicit** agent-context contract explicit. It describes the
as-built behavior of `agent/context.py`; it introduces **no behavior change**.

## Why

`agent/context.py` is the agent's only window into the frozen repo: it loads the knowable-at-T
context file, derives a tamper-proof `repo_layout` from the checkout, degrades to a git-only
rebuild on unreadable input, mirrors `benchmark/leakage.py`'s forward-reference masking locally
(the #916/#937/#1307 alignment invariant), and shapes the agent-facing prompt view (#493 list
guards, `labels_as_of_t` semantics, truncation-flag backlog clearing). Every sibling agent module
has a spec (006, 007, 009, 010; 008 in flight) and the benchmark-side producer is being
documented as Spec 081 — this module's contract is the remaining gap. Pinning it catches silent
regressions in exactly the places past bugs lived (#493, #749, #916/#937, #1307).

## User stories

1. **As a benchmark operator**, I can rely on the agent seeing only knowable-at-T content — on
   both the frozen-file and git-fallback paths — with identical scrubbing either way.
2. **As an agent author**, I get a stable prompt-view shape (list keys always present, labels
   only when historically accurate) that malformed frozen input cannot crash.
3. **As a reviewer**, the fallback arms, every warning, and the layout exclusion rules are
   written down.

## Acceptance criteria (EARS)

### Constants and alignment binding

- `CONTEXT_FILE` SHALL be `".vanguarstew_context.json"`.
- `README_PROBE_NAMES` SHALL be `("README.md", "README.rst", "README.txt", "README",
  "docs/README.md")` in priority order, and `benchmark/freeze.py` SHALL import this tuple (the
  freeze and the fallback probe the same names).
- `REPO_LAYOUT_LIMIT` SHALL be `40`; `_LAYOUT_EXCLUDED` SHALL be exactly
  `{CONTEXT_FILE, ".git"}`.
- `_agent_issue_pr_list` SHALL be the same function object as `_agent_context_list`
  (backward-compatible alias).

### Forward-reference scrubbing (`_mask_forward_refs`)

- WHEN `text` is not a `str` THEN the result SHALL be `""`; an empty string SHALL be returned
  unchanged.
- GitHub deep-links (`issues|pull|pulls|commit|commits|compare|releases|tag|tags|tree|blob|`
  `milestone|milestones|discussions`) SHALL be masked to `<link>`, including scheme-less and
  `www.` forms; a bare `owner/repo` URL SHALL be preserved; a look-alike host
  (`notgithub.com/...`) SHALL be preserved.
- Trailing sentence punctuation (`.,;!`) SHALL be peeled back out of the mask; query/fragment
  separators SHALL remain masked.
- Issue/PR back-references (`#123`) SHALL become `#ref`.
- A word-bounded hex run of 7–40 chars, or exactly 64 chars, containing at least one hex letter
  SHALL become `<sha>`; runs of 41–63 chars and all-numeric runs SHALL be preserved.
- The masking SHALL be structurally identical to `benchmark.leakage.strip_forward_refs`
  (alignment guarded by `tests/test_scrubber_alignment.py`) without importing from
  `benchmark/`.

### Repo layout (`repo_layout`)

- WHEN `repo_path` is not a `str` or is empty THEN the result SHALL be `[]` (no warning).
- WHEN `limit` is a `bool`, not an `int`, or negative THEN it SHALL fall back to
  `REPO_LAYOUT_LIMIT`; a `limit` of `0` SHALL yield `[]`.
- Entries SHALL be the checkout's top-level names, sorted, with directories suffixed `/`;
  names in `_LAYOUT_EXCLUDED` SHALL be omitted and SHALL NOT consume the cap; at most `limit`
  entries SHALL be returned.
- WHEN the path cannot be listed (`OSError` — missing, not a directory, unreadable — or
  `ValueError` from a NUL byte) THEN the result SHALL be `[]` after a
  `logging.warning` on `agent.context` of the form
  `repo_layout: cannot list {path} ({ExcType}: {exc}); continuing without repo layout`.

### Layout attachment (`_with_repo_layout`)

- WHEN `context` is not a `dict` THEN it SHALL be returned unchanged (the same object).
- OTHERWISE the result SHALL be a **new** dict with `repo_layout` set to the derived layout —
  always derived from the checkout, never read from the context file, so a `repo_layout` key
  present in the file SHALL be overridden.

### Context loading (`load_context`)

- WHEN `CONTEXT_FILE` exists in `repo_path` and parses as JSON THEN its content SHALL be
  returned with the derived `repo_layout` attached (a JSON value that is not an object SHALL be
  passed through unchanged, relying on `context_for_agent`'s downstream guard).
- WHEN the file is present but unreadable — `json.JSONDecodeError` (truncated/invalid),
  `UnicodeDecodeError` (non-UTF-8/binary), or `OSError` (including `PermissionError`,
  `IsADirectoryError`) — THEN `load_context` SHALL log a `logging.warning` on `agent.context`
  of the form `load_context: {path} unreadable ({size} bytes, {ExcType}: {exc}); rebuilding
  from git` (size `-1` when unstattable) and SHALL return the git-only fallback context with
  the derived `repo_layout` attached.
- WHEN the file is absent THEN the git-only fallback SHALL be used, with the derived
  `repo_layout` attached.
- Only the listed exception types SHALL be caught — never a bare `Exception`.

### Agent list guard (`_agent_context_list`)

- A `list` SHALL be returned as the same object; `None` SHALL yield `[]` silently.
- Any other value SHALL yield `[]` after a `logging.warning` of the form
  `context_for_agent: {field} is {type}, not a list; treating as empty`.

### Agent-facing view (`context_for_agent`)

- WHEN `context` is not a `dict` THEN the result SHALL be `{}` after a `logging.warning` of the
  form `context_for_agent: context is {type}, not a dict; treating as empty`, where `{type}` is
  the literal `None` for `None` input (not `NoneType`).
- The input SHALL NOT be mutated; unknown top-level keys SHALL be preserved in the copy.
- For `open_issues` / `open_prs`: a non-dict entry SHALL be passed through unchanged after a
  `logging.warning` of the form `context_for_agent: non-dict {key} entry at index {idx}
  ({type}: {value!r}); passing through`; a dict entry SHALL be copied, and its `labels` key
  SHALL be removed unless the entry's `labels_as_of_t` is the boolean `True` (identity — a
  truthy `1` or `"yes"` SHALL NOT keep labels). WHEN the flag is `True` THEN `labels` SHALL be
  kept verbatim and the flag itself retained.
- `open_issues`, `open_prs`, `recent_commits`, `releases`, `milestones`, and `labels` SHALL all
  be present in the output as lists (absent or malformed inputs coerced via the list guard).
- WHEN `_issues_truncated` is the boolean `True` THEN both `open_issues` and `open_prs` SHALL
  be emptied; `_milestones_truncated` SHALL empty `milestones`; `_releases_truncated` SHALL
  empty `releases`. A truthy non-`True` flag (e.g. `1`) SHALL NOT trigger the clearing.

### Git-only fallback (`_context_from_git`)

- WHEN the repo has no commits (HEAD does not resolve) THEN it SHALL raise `RuntimeError` with
  the message `git-only context fallback: {repo_path} has no commits (HEAD does not resolve)`.
- `recent_commits` SHALL carry at most 50 rows of `{"sha": <10-char id>, "subject": <scrubbed>}`.
- `releases` SHALL carry the last 10 reachable tags whose creator date is on or before T
  (a tag created after T from a pre-T commit SHALL be excluded — #749), each as
  `{"tag": <scrubbed>}`.
- `readme_excerpt` SHALL come from the first **non-empty** `README_PROBE_NAMES` candidate (an
  empty higher-priority README SHALL NOT shadow a populated lower-priority one — the #916/#937
  alignment), truncated to 4000 characters and scrubbed; `""` when none is found.
- The result SHALL carry `frozen_at` (`{"commit": <10-char id>, "date": <ISO or None>}`), empty
  `open_issues` / `open_prs` / `labels` / `milestones` lists, `_source: "git"`, and
  `_forward_signal_scrubbed: True` (#1307 provenance).

### Scope of I/O

- `_mask_forward_refs`, `_agent_context_list`, and `context_for_agent` SHALL perform no I/O.
- `load_context` / `repo_layout` / `_context_from_git` SHALL read only the given checkout
  (context file, directory listing, local git) — never the network.

## Out of scope

- The benchmark-side producer `benchmark/github_context.py` (Spec 081 in flight) and the frozen
  artifact's field semantics.
- `benchmark.leakage.strip_forward_refs` internals (Specs 003/022); the cross-module alignment
  itself is guarded by `tests/test_scrubber_alignment.py`.
- The `load_context` oversized-int-literal arm (a plain `ValueError` from `json.load`) —
  tracked separately by #1494; this spec pins only the documented catch set.
- Prompt rendering of the context (`agent/decider.py` / `agent/planner.py` /
  `agent/philosophy.py`, Specs 006/007).

## Verification

- `tests/test_spec_011_agent_context.py` exercises each EARS block above: the constants and the
  freeze-import binding; every scrubber arm with literal expected strings; `repo_layout`
  path/limit coercion (bool/negative/zero), exclusion, sorting, directory suffixing, cap, and
  the warning via `caplog`; `_with_repo_layout` identity pass-through and file-value override;
  all three `load_context` arms (valid, each unreadable variant with the warning format,
  absent) plus the non-dict JSON passthrough; the list-guard and `context_for_agent` semantics
  (`None` wording, indexed row warnings, `labels_as_of_t` and truncation-flag identity checks,
  always-present list keys, purity); and the git-fallback contract (empty-repo `RuntimeError`
  literal, commit/tag row shapes and caps, future-dated tag exclusion, README priority and
  empty-file skip, the 4000-char cap, and the provenance keys).
- Broader integration coverage (prompt renderers, cross-builder alignment, the CLI paths)
  remains in `tests/test_context.py` and `tests/test_scrubber_alignment.py`.
