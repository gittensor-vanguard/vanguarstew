# Plan 006 — agent decision (`decide()`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #629

How the [spec](./spec.md) maps onto `agent/decider.py` as-built. No new product code; this
records the contract surface + normalization flow so future decider changes are reviewed
against a plan.

## Architecture / control flow

```
decide(context, philosophy, request, llm)
  ├─ build user prompt (philosophy + _render(context) + request + JSON schema hint)
  ├─ out = llm.chat_json(SYSTEM, user, stub=offline_stub)
  ├─ IF out is not a dict → out = copy(offline_stub)
  └─ normalize each field:
       action        ← _normalize_action(out["action"])
       labels        ← _normalize_labels(out["labels"])
       reviewer      ← _normalize_reviewer(out["reviewer"])
       rationale     ← _normalize_rationale(out["rationale"])
       patch         ← _normalize_patch(out["patch"])
       version_bump  ← _normalize_version_bump(out["version_bump"])
```

## Data model

### Inputs

| Input | Type | Role |
| ----- | ---- | ---- |
| `context` | `dict` | frozen repo state (rendered via `context_for_agent`) |
| `philosophy` | `dict` | inferred maintainer direction |
| `request` | `str` | concrete decision prompt (e.g. "review PR #1") |
| `llm` | `LLM` | managed-inference client (`chat_json` with offline stub) |

### Output (always all keys present)

| Field | Normalized type | Notes |
| ----- | --------------- | ----- |
| `action` | `str` ∈ `VALID_ACTIONS` | unknown/non-string → `plan` |
| `labels` | `list[str]` | triage labels; else `[]` |
| `reviewer` | `str \| None` | suggested reviewer |
| `version_bump` | `major\|minor\|patch \| None` | release prediction input for scoring |
| `patch` | `str \| None` | unified diff when patching |
| `rationale` | `str` | decision-process judge reads this |

### Action vocabulary & synonyms

| Canonical | Synonyms mapped |
| --------- | ---------------- |
| `merge` | `approve`, `approved`, `lgtm` |
| `request-changes` | `request changes`, `request_changes`, `requested-changes` |
| `assign-reviewer` | `assign_reviewer`, `assign reviewer` |
| `close` | `closed` |
| `triage` | `triaged` |
| `label` | `labeled`, `labelled` |
| *(anything else / non-string)* | `plan` |

### Version bump nullish tokens

`none`, `null`, `n/a`, blank → `None`. Unknown strings (e.g. `micro`, `yolo`) → `None`.

## The invariants this pins

- **Vocabulary safety:** only declared actions reach scoring; everything else becomes `plan`.
- **Stable shape:** six keys, always present, always normalized types.
- **Coercion not crash:** malformed LLM types degrade field-by-field; a bad `action` does not
  block normalization of `labels`/`reviewer`/etc.
- **Offline CI:** stub path returns the same shape deterministically.

## Verification strategy

`tests/test_spec_006_decision.py` (this PR) maps one test group per EARS section with scripted
fake LLMs; unit helpers are also exercised directly where that isolates a rule. Broader
behavior stays in `tests/test_decider.py`.

## Out of scope for this plan

Changing decider behavior, the planner/philosophy contracts, or review-agent output. Code
changes follow the SDD loop in their own specs/PRs.
