# Plan 007 — agent planner (`plan_next_actions()`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #657

How the [spec](./spec.md) maps onto `agent/planner.py` as-built. No new product code; this
records the contract surface + normalization/reconciliation flow so future planner changes are
reviewed against a plan.

## Architecture / control flow

```
plan_next_actions(context, philosophy, n, llm)
  ├─ IF context is not a dict → context = {}
  ├─ build user prompt (philosophy + _render(context) + _pr_queue_note(context) + schema hint)
  ├─ plan = llm.chat_json(SYSTEM, user, stub=_offline_plan_stub(context, n))
  ├─ IF plan is dict → unwrap plan["plan"] or plan["actions"] via _plan_list
  ├─ plan = _normalize_plan(plan if list else [])
  └─ return reconcile_plan_with_queue(plan, context, n)

reconcile_plan_with_queue(plan, context, n)
  ├─ prs = _pr_queue(context)          # open PRs with string titles only
  ├─ plan = _normalize_plan(plan)
  ├─ IF no prs → return plan[:n]
  ├─ for each item:
  │    ├─ pr = _matched_pr(item, prs)
  │    ├─ IF pr already seen → skip (collapse duplicates)
  │    ├─ IF pr matched and not _is_review_item → down-weight to triage + restates_pr
  │    └─ append item
  ├─ IF no PR addressed → prepend review item for prs[0]
  └─ return out[:n]
```

## Data model

### Inputs

| Input | Type | Role |
| ----- | ---- | ---- |
| `context` | `dict` | frozen repo state (`open_prs`, commits, issues, …) |
| `philosophy` | `dict` | inferred maintainer direction |
| `n` | `int` | max plan items to return |
| `llm` | `LLM` | managed-inference client (`chat_json` with offline stub) |

### Output (list of plan items)

| Field | Normalized type | Notes |
| ----- | --------------- | ----- |
| `title` | `str` (required) | short imperative title |
| `kind` | `str` ∈ `_PLAN_KINDS` | unknown → `triage` |
| `rationale` | `str` (optional) | omitted when blank |
| `theme` | `str` (optional) | omitted when blank |
| `files` | `list[str]` (optional) | omitted when empty |
| `restates_pr` | `int` (optional) | set by queue reconciliation |

### Plan kinds

`feature`, `bugfix`, `refactor`, `docs`, `release`, `dep`, `triage` — anything else becomes
`triage`.

### PR matching priority (`_matched_pr`)

1. Explicit reference (`PR #N`, `pull request N`, or validated bare `#N`)
2. Full-subject phrase in title/rationale (longest title wins among nested titles)
3. Significant-token overlap (≥2 shared tokens; single-token PR titles excluded)

### Offline stub (`_offline_plan_stub`)

One review item per open PR with a string title; if the queue is empty, a single
`"offline stub action"` triage item. Capped to `n`.

## The invariants this pins

- **Stable shape:** every returned item has `title` + `kind`; optional fields omitted when blank.
- **Queue honor:** open PRs are never silently ignored when reconciliation runs.
- **Coercion not crash:** malformed LLM types degrade item-by-item; bad `open_prs` / plan
  containers become empty lists.
- **Ordinal safety:** bare `#N` in prose does not attach to unrelated PRs.
- **Offline CI:** stub path returns the same shape deterministically.

## Verification strategy

`tests/test_spec_007_planner.py` (this PR) maps one test group per EARS section with scripted
fake LLMs; unit helpers are also exercised directly where that isolates a rule. Broader
behavior stays in `tests/test_planner.py`.

## Out of scope for this plan

Changing planner behavior, the decider/philosophy contracts, or review-agent output. Code
changes follow the SDD loop in their own specs/PRs.
