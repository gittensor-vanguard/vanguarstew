# Spec 007 — the agent planner (`plan_next_actions()`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #657
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint seam),
  [`specs/006-agent-decision`](../006-agent-decision/spec.md) (decision step follows planning)

This spec makes the **existing, implicit** planner contract explicit. It describes the
as-built behavior of `agent/planner.py`; it introduces **no behavior change**. The planner
emits the next maintainer actions the benchmark judges against revealed history — on
direction/theme, not on naming exact PRs — so its normalization and open-PR queue
reconciliation must be written down and verified.

## Why

A malformed LLM plan (`title` as a number, `kind` as free text, `files` as a bare string,
`open_prs` as a truthy non-list) must not abort a replay run or silently skip the visible PR
queue. The planner already coerces plan items and reconciles them with the frozen queue;
making that contract explicit lets reviewers check planner changes against intent and gives M5
a reviewable definition of the planning surface.

## User stories

1. **As the validator**, I receive a normalized plan list capped to `n` — so scoring never
   sees arbitrary shapes or unbounded item counts.
2. **As an agent developer**, I know how open-PR queue reconciliation works (duplicate
   down-weight, ignored-queue prepend, redundant collapse) — so I optimize real maintainer
   plans, not prompt luck.
3. **As a reviewer**, plan normalization and PR-matching rules are written down — so a change
   to `planner.py` is checked against the spec.

## Acceptance criteria (EARS)

### Plan list shape

- `plan_next_actions(context, philosophy, n, llm)` SHALL return a `list` of normalized plan
  item dicts, capped to at most `n` items.
- IF `context` is not a `dict` THEN `plan_next_actions()` SHALL fall back to the offline stub
  path (empty context) and still return a list.
- IF the LLM returns a dict wrapper (`{"plan": [...]}` or `{"actions": [...]}`) THEN the
  planner SHALL unwrap the list field when it is a list; otherwise treat as empty.
- IF the LLM returns a non-list plan payload THEN normalization SHALL treat it as empty, not
  raise.

### Plan item normalization

- Each normalized item SHALL contain at least `title` (non-empty `str`) and `kind` (one of
  `feature`, `bugfix`, `refactor`, `docs`, `release`, `dep`, `triage`).
- WHEN `kind` is missing, blank, or unknown THEN the system SHALL default to `triage`.
- WHEN `title` is missing, blank after strip, or the item is not a dict THEN the item SHALL
  be dropped.
- `rationale` and `theme` SHALL be optional stripped strings; blank values SHALL be omitted.
- `files` SHALL be coerced to `list[str]` when present; blank entries SHALL be skipped.
- WHEN `files` is a bare string THEN the system SHALL wrap it as a one-element list (after
  strip); blank strings SHALL yield omission of the key.
- WHEN `files` is any other non-list type THEN the system SHALL return `[]` and omit the key
  (with a warning logged).

### Open-PR queue inputs

- `open_prs` in `context` SHALL be treated as a list only when it is actually a `list`; a
  truthy non-list SHALL be treated as no queue.
- PR entries without a string `title` SHALL be skipped for queue display and matching.

### Queue reconciliation

- WHEN there are no open PRs (or none with valid titles) THEN `reconcile_plan_with_queue()`
  SHALL pass the normalized plan through unchanged, capped to `n`.
- WHEN a plan item legitimately addresses an open PR and already reads as a review item
  (`kind == triage` or review/merge vocabulary in the title) THEN the item SHALL be left
  intact (no `restates_pr` flag).
- WHEN a plan item restates open-PR work without review framing THEN the system SHALL
  down-weight it to `kind == triage`, set `restates_pr`, and supply a review rationale.
- WHEN multiple plan items target the same open PR THEN only the first SHALL survive.
- WHEN no plan item addresses any open PR THEN the system SHALL prepend a review item for
  the top queued PR (`restates_pr`, `theme == "PR queue"`).
- Reconciliation output SHALL always be capped to `n` items.

### PR reference matching

- Explicit `PR #N` / `pull request N` references SHALL be authoritative over bare `#N`.
- A bare `#N` SHALL match an open PR only when the item reads as a PR reference or its
  content substantively matches the PR (subject phrase or strong token overlap).
- A bare `#N` used as an ordinal ("our #7 priority") SHALL NOT hijack an unrelated open PR.
- WHEN an explicit reference names a PR not in the open queue THEN the item SHALL NOT fall
  back to a different open PR via token overlap.
- Single-token PR titles SHALL NOT match on token overlap alone.
- WHEN several PR titles nest as substrings THEN the longest matching subject phrase SHALL
  win.

### Offline determinism

- WHEN the LLM is offline (`VANGUARSTEW_OFFLINE=1` / `api_key == "offline"`) THEN
  `plan_next_actions()` SHALL return a deterministic stub that prioritizes visible open PRs
  (review items per queued PR, else a single offline stub action), after normalization and
  reconciliation — exercisable in CI without a key.

### Robustness (per constitution)

- IF any LLM-emitted field has an unexpected type THEN normalization SHALL coerce or drop,
  not raise — per `AGENTS.md` → *Benchmark integrity*.

## Out of scope

- **Decision** output contract — covered by [`specs/006-agent-decision`](../006-agent-decision/spec.md).
- **Philosophy inference** — a separate agent step.
- Changing planner behavior — code changes follow the SDD loop in their own PRs; this spec
  documents the as-built surface only.

## Verification

- `tests/test_spec_007_planner.py` (this PR) exercises each EARS block against the real
  `plan_next_actions()`, `reconcile_plan_with_queue()`, and normalization helpers.
- Broader unit coverage remains in `tests/test_planner.py`.
