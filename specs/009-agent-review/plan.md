# Plan 009 — agent review (`review_pr()`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #689

How the [spec](./spec.md) maps onto `agent/review.py` as-built. No new product code; this
records the contract surface + normalization flow so future review changes are reviewed against
a plan.

## Architecture / control flow

```
review_pr(pr, philosophy, llm)
  ├─ IF pr is not a dict → return fixed error dict (no LLM call)
  ├─ extract string file paths from pr["files"] when it is a list
  ├─ build user prompt (philosophy + PR metadata + diff + schema hint)
  ├─ out = llm.chat_json(SYSTEM, user, stub=offline_stub)
  └─ return _normalize_review(out, stub)

_normalize_review(out, stub)
  ├─ IF out is not a dict → return copy(stub)
  └─ normalize each field:
       action          ← _normalize_review_action(out["action"])
       value_label     ← _normalize_value_label(out["value_label"])
       scope_ok        ← _normalize_bool(out["scope_ok"], stub["scope_ok"])
       tests_present   ← _normalize_bool(out["tests_present"], stub["tests_present"])
       summary         ← _normalize_text(out["summary"], "")
       concerns        ← _normalize_concerns(out["concerns"])
       recommendation  ← _normalize_text(out["recommendation"], "")
```

## Data model

### Inputs

| Input | Type | Role |
| ----- | ---- | ---- |
| `pr` | `dict` | live PR metadata (`number`, `title`, `body`, `files`, `diff`, …) |
| `philosophy` | `dict \| None` | inferred maintainer direction (optional prompt context) |
| `llm` | `LLM` | managed-inference client (`chat_json` with offline stub) |

### Output (always all keys present)

| Field | Normalized type | Notes |
| ----- | --------------- | ----- |
| `action` | `str` ∈ `ACTIONS` | unknown/non-string → `comment` |
| `value_label` | `str` ∈ `VALUE_LABELS` | unknown/non-string → `mult:contribution` |
| `scope_ok` | `bool` | scope-fit signal |
| `tests_present` | `bool` | stub derives from `tests/` paths when offline |
| `summary` | `str` | one-sentence PR summary |
| `concerns` | `list[str]` | actionable concerns; else `[]` |
| `recommendation` | `str` | maintainer advice |

### Action vocabulary and synonyms

| Canonical | Synonyms mapped |
| --------- | ---------------- |
| `merge` | `approve`, `approved`, `accept`, `accepted`, `lgtm` |
| `request-changes` | `request changes`, `request_changes`, `requested-changes`, `changes requested`, `changes_requested` |
| `reject` | `decline`, `deny`, `closed`, `close` |
| `comment` | `abstain`, `hold` |
| *(anything else / non-string)* | `comment` |

### Value-label tiers

`perf:pending` (the PR touches `agent/` — its real `perf:*` band awaits a live
`scripts/score_pr_delta.py` run, this module never predicts it), `mult:contribution` (flat
rate for everything else) — anything else, including a retired `mult:*` tier from the old
ladder, becomes `mult:contribution`.

## EARS → test mapping

| Spec section | Test group in `test_spec_009_review.py` |
| ------------ | ---------------------------------------- |
| Review dict shape | `test_review_*_shape`, `test_non_dict_pr_*`, `test_review_falls_back_when_llm_returns_non_dict` |
| Action normalization | `test_valid_actions_*`, `test_action_synonyms_*`, `test_unknown_or_non_string_action_*` |
| Value-label normalization | `test_value_label_*` |
| Boolean normalization | `test_bool_*` |
| Text normalization | `test_text_*` |
| Concerns normalization | `test_concerns_*` |
| PR files input | `test_files_*`, `test_offline_tests_present_*` |
| Offline determinism | `test_offline_review_*` |
| Robustness | `test_review_coerces_all_malformed_fields_*`, `test_bad_action_does_not_block_*` |

## The invariants this pins

- **Vocabulary safety:** only declared actions and value-label tiers reach triage.
- **Stable shape:** seven keys, always present, always normalized types.
- **Coercion not crash:** malformed LLM types degrade field-by-field.
- **Offline CI:** stub path returns the same shape deterministically.

## Verification strategy

`tests/test_spec_009_review.py` (this PR) maps one test group per EARS section with scripted
fake LLMs; unit helpers are also exercised directly where that isolates a rule. Broader
behavior stays in `tests/test_review.py`.

## Out of scope for this plan

Changing review behavior, the CLI fetch path, or other agent-step contracts. Code changes follow
the SDD loop in their own specs/PRs.
