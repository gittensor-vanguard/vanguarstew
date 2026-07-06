# Plan 010 — managed-inference LLM client (`LLM`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #716

How the [spec](./spec.md) maps onto `agent/llm.py` as-built. No new product code; this records
the contract surface so future LLM-client changes are reviewed against a plan.

## Architecture / control flow

```
LLM.__init__(model, api_base, api_key, timeout)
  ├─ strip trailing slash from api_base
  ├─ resolve timeout from arg → TAU_AGENT_TIMEOUT_SECONDS → 120
  └─ offline = VANGUARSTEW_OFFLINE=1 OR not api_base OR api_key == "offline"

LLM.chat(system, user)
  ├─ IF offline → return json.dumps({"_offline": True})
  └─ ELSE POST {api_base}/chat/completions (temperature=0) → message content

LLM.chat_json(system, user, stub=None)
  ├─ IF offline → return stub if stub is not None else {}
  └─ ELSE extract_json(chat(system, user))

extract_json(text)
  ├─ IF text is None → raise ValueError
  ├─ try fenced ``` blocks → _pick_best_json
  ├─ try json.loads(text) verbatim
  ├─ scan _iter_top_level_spans → _pick_best_json
  └─ IF nothing parsed → raise ValueError
```

## Data model

### Inputs

| Input | Type | Role |
| ----- | ---- | ---- |
| `model` | `str \| None` | validator-managed model id (default placeholder when unset) |
| `api_base` | `str \| None` | OpenAI-compatible base URL |
| `api_key` | `str \| None` | bearer token (`"offline"` forces stub mode) |
| `timeout` | `float \| None` | request timeout seconds |

### Offline detection (any triggers offline)

| Condition | Result |
| --------- | ------ |
| `VANGUARSTEW_OFFLINE=1` | offline |
| `api_base` missing/blank | offline |
| `api_key == "offline"` | offline |

### `_pick_best_json` rank

1. Prefer `dict` over `list` (object beats array).
2. Prefer longer `json.dumps(..., separators=(",", ":"))` length.
3. On equal rank, prefer the **last** candidate (reverse + max).

## EARS → test mapping

| Spec section | Test group in `test_spec_010_llm.py` |
| ------------ | ------------------------------------- |
| Managed-inference parameters | `test_offline_when_*`, `test_api_base_*` |
| Offline `chat()` | `test_offline_chat_*` |
| Offline `chat_json()` | `test_offline_chat_json_*` |
| JSON extraction order | `test_extract_json_fenced_*`, `test_extract_json_raw_*`, `test_extract_json_spans_*` |
| JSON tie-breaking | `test_pick_best_json_*`, `test_extract_json_prefers_*` |
| Robustness | `test_extract_json_skips_*`, `test_extract_json_raises_*` |

## The invariants this pins

- **Policy compliance:** no inference without validator-supplied endpoint/key (except offline).
- **Deterministic CI:** offline path never opens a socket; stubs pass through unchanged.
- **Robust parsing:** prose-wrapped JSON is recovered with documented tie-break rules.

## Verification strategy

`tests/test_spec_010_llm.py` (this PR) maps one test group per EARS section. Broader smoke
coverage stays in `tests/test_smoke.py`.

## Out of scope for this plan

Codex backend, online transport error handling, and changes to extraction behavior.
