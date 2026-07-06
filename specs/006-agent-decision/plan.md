# Plan 006 — agent decision contract (`decide()`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #629

How the [spec](./spec.md) maps onto `agent/decider.py` as-built. No new product code; this records
the contract surface so future decider changes are reviewed against a plan.

## Architecture

```
decide(context, philosophy, request, llm) -> dict
  ├─ user = philosophy + _render(context_for_agent(context)) + request + JSON key spec
  ├─ out = llm.chat_json(SYSTEM, user, stub=STUB)        # STUB returned verbatim when offline
  ├─ if not isinstance(out, dict): out = STUB
  └─ normalize each field:
       action        → _normalize_action        (VALID_ACTIONS ∪ synonyms; else "plan")
       labels        → _normalize_labels         (→ list[str])
       reviewer      → _normalize_reviewer        (→ str | None)
       rationale     → _normalize_rationale       (→ str, never None)
       patch         → _normalize_patch           (→ str | None)
       version_bump  → _normalize_version_bump    (→ major/minor/patch | None)
```

## Data model (output)

| Key | Type | Normalizer | Notes |
| --- | ---- | ---------- | ----- |
| `action` | one of `VALID_ACTIONS` | `_normalize_action` | synonym-mapped; non-string/unknown → `plan` |
| `labels` | `list[str]` | `_normalize_labels` | bare string → `[str]`; junk dropped |
| `reviewer` | `str \| None` | `_normalize_reviewer` | blank → `None` |
| `version_bump` | `major`/`minor`/`patch`/`None` | `_normalize_version_bump` | mirrors `score._norm_bump` |
| `patch` | `str \| None` | `_normalize_patch` | blank → `None` |
| `rationale` | `str` | `_normalize_rationale` | never `None`; judged text |

`VALID_ACTIONS` = `merge, request-changes, reject, triage, assign-reviewer, release, plan, patch,
close, label`. `_BUMP_LEVELS` = `{major, minor, patch}`.

## The invariants this pins

- **Fixed shape:** all six keys always present, canonical types — offline/non-dict → stub then normalize.
- **Fail-safe action:** unknown/non-string `action` → `plan`, never crash.
- **Bump parity:** `version_bump` normalization matches the scorer so predictions aren't dropped.

## Verification strategy

`tests/test_spec_006_decision.py` (this PR) exercises each normalizer plus an end-to-end
`decide()` over a malformed-output fake LLM; broader behavior is in `tests/test_decider.py`.

## Out of scope for this plan

Changing any decider behavior, the planner/philosophy steps, or the review path. Code changes
follow the SDD loop in their own specs/PRs.
