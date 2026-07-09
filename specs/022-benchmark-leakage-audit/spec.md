# Spec 022 — frozen-context leakage audit (`audit_context`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Issue:** #841
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/003-leakage-integrity`](../003-leakage-integrity/spec.md) (`strip_forward_refs` / `scrub_context`)

This spec makes the **existing, implicit** leakage-audit contract explicit. It describes the
as-built behavior of `benchmark/leakage_audit.py`; it introduces **no behavior change**. The
audit verifies that frozen contexts are free of residual forward references before agents see
them — so detection rules and headline robustness must be written down and verified.

## Why

`scrub_context` masks issue refs, GitHub links, and SHAs, but regressions can leave leaks behind.
`audit_context` reuses the same scrub rules for detection. Making that contract explicit lets
reviewers check audit changes against intent.

## User stories

1. **As a leakage reviewer**, I can run `audit_context` and get structured findings with
   `location`, `value`, and `masked` — so every leak is pinpointed.
2. **As a CI operator**, `is_clean` and `audit_headline` give stable pass/fail summaries — so
   malformed inputs never crash the audit pipeline.
3. **As a maintainer**, logging and non-dict handling are written down — so audit regressions are
   caught by contract tests.

## Acceptance criteria (EARS)

### Audited fields

- `audit_context(context)` SHALL inspect these scrubbable fields when `context` is a `dict`:
  - `readme_excerpt` (string text),
  - `recent_commits[*].subject`,
  - `open_issues[*].title`,
  - `open_prs[*].title`,
  - `milestones[*].title`,
  - `releases[*].tag` and `releases[*].name`.
- Each finding SHALL be a dict with keys: `location`, `value`, `masked`.
- A finding SHALL be emitted only when `strip_forward_refs(value) != value` for a non-empty string
  field.
- An empty findings list means the context is clean.

### Non-dict and malformed context handling

- IF `context` is not a `dict` THEN `audit_context()` SHALL return `[]` without raising.
- WHEN a list field (`recent_commits`, `open_issues`, `open_prs`, `milestones`, `releases`) is not
  a list THEN that field SHALL be skipped (not raise).
- WHEN a list row is not a `dict`, or the audited text key is missing, or the text is not a
  non-empty string THEN that row SHALL be skipped.
- WHEN a text field is a non-string (for example a list embedded as a title) THEN that row SHALL
  be skipped.

### Clean gate

- `is_clean(context)` SHALL return `True` when `audit_context(context)` is empty.
- `is_clean(context)` SHALL return `False` when any finding is present.
- WHEN `context` is not a `dict` THEN `is_clean()` SHALL return `True` (no findings).

### Scrub alignment

- WHEN `context` is passed through `scrub_context()` THEN `audit_context(scrubbed)` SHALL return
  `[]` and `is_clean(scrubbed)` SHALL be `True`.

### False-positive guard

- Plain numeric prose without forward-reference tokens (for example throughput figures) SHALL NOT
  produce findings.

### Findings-list sanitization (`_findings_list`)

- `_findings_list(findings)` SHALL return the input list when `findings` is a `list`.
- WHEN `findings` is `None` THEN the function SHALL return `[]` silently (no log).
- WHEN `findings` is an empty list THEN the function SHALL return `[]` silently (no log).
- WHEN `findings` is a non-list container (int, float, bool, dict, str, tuple, etc.) THEN the
  function SHALL return `[]` and log a warning at logger `benchmark.leakage_audit` containing the
  phrase `findings is` and the container type name.

### Audit headline

- `audit_headline(findings)` SHALL return a one-line human summary prefixed with `audit_context:`.
- WHEN `_findings_list(findings)` is empty THEN the headline SHALL read
  `audit_context: clean (no forward-reference leaks)`.
- WHEN `_findings_list(findings)` is non-empty THEN the headline SHALL include the finding count.
- WHEN `findings` is a non-list container THEN `audit_headline()` SHALL NOT raise; it SHALL behave
  as if there are zero findings and log the same warning as `_findings_list`.

### Pure evaluation

- The module SHALL perform no network I/O.
- `audit_context()` SHALL NOT mutate the input `context` dict or nested rows.

## Out of scope

- Changing `strip_forward_refs` rules (`benchmark/leakage.py`) — spec 003.
- Git-only agent fallback masking (`agent/context.py`).
- Adding new audited fields — product changes in separate PRs.

## Verification

- `tests/test_spec_022_leakage_audit.py` (this PR) exercises each EARS block above.
- Broader CLI coverage remains in `tests/test_leakage_audit.py`.
