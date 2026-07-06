# Plan 008 — agent philosophy (`infer_philosophy()`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #672

How the [spec](./spec.md) maps onto `agent/philosophy.py` as-built. No new product code; this
records the contract surface + normalization flow so future philosophy changes are reviewed
against a plan.

## Architecture / control flow

```
infer_philosophy(context, llm)
  ├─ IF context is not a dict → return minimal fallback {summary, values}
  ├─ build user prompt (FEWSHOT + _render(context) + JSON schema hint)
  ├─ out = llm.chat_json(SYSTEM, user, stub=offline_stub)
  └─ return _normalize_philosophy(out, stub)

_normalize_philosophy(out, stub)
  ├─ IF out is not a dict → return copy(stub)
  └─ normalize each field:
       summary   ← _normalize_text(out["summary"], stub["summary"])
       values    ← _normalize_string_list(out["values"])
       merge_bar ← _normalize_text(out["merge_bar"], stub["merge_bar"])
       direction ← _normalize_text(out["direction"], stub["direction"])
       evidence  ← _normalize_string_list(out["evidence"])
```

## Data model

### Inputs

| Input | Type | Role |
| ----- | ---- | ---- |
| `context` | `dict` | frozen repo state (rendered via `context_for_agent`) |
| `llm` | `LLM` | managed-inference client (`chat_json` with offline stub) |

### Output (full LLM path)

| Field | Normalized type | Notes |
| ----- | --------------- | ----- |
| `summary` | `str` | one-sentence characterization |
| `values` | `list[str]` | guiding values (e.g. `conservative`, `feature-first`) |
| `merge_bar` | `str` | what tends to get merged vs rejected |
| `direction` | `str` | where the codebase appears to be heading |
| `evidence` | `list[str]` | concrete signals used |

### Non-dict context fallback

| Field | Value |
| ----- | ----- |
| `summary` | `"offline stub philosophy"` |
| `values` | `["triage"]` |

Only these two keys are returned — the LLM is not invoked.

### Offline stub defaults

| Field | Value |
| ----- | ----- |
| `summary` | `"offline stub philosophy"` |
| `values` | `[]` |
| `merge_bar` | `"unknown (offline)"` |
| `direction` | `"unknown (offline)"` |
| `evidence` | `[]` |

## The invariants this pins

- **Stable shape:** five keys on the LLM path; minimal two-key fallback for bad context.
- **Coercion not crash:** malformed LLM types degrade field-by-field; a bad `summary` does not
  block normalization of `values`/`evidence`.
- **List safety:** `values` and `evidence` are always `list[str]`, never bare strings or mixed
  types leaking through.
- **Offline CI:** stub path returns the same shape deterministically.

## Verification strategy

`tests/test_spec_008_philosophy.py` (this PR) exercises one test group per EARS section with
scripted fake LLMs; unit helpers are also exercised directly where that isolates a rule.
Broader behavior stays in `tests/test_philosophy.py`.

## Out of scope for this plan

Changing philosophy behavior, the planner/decider contracts, or review-agent output. Code
changes follow the SDD loop in their own specs/PRs.
