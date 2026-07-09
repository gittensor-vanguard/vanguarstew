# Spec 010 — the managed-inference LLM client (`LLM`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #716
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint passes managed-inference params),
  [`specs/006-agent-decision`](../006-agent-decision/spec.md) (decider calls `chat_json`)

This spec makes the **existing, implicit** LLM client contract explicit. It describes the
as-built behavior of `agent/llm.py`; it introduces **no behavior change**. Every agent step
depends on this client for managed inference and offline CI — so its offline detection, stub
behavior, and JSON extraction rules must be written down and verified.

## Why

The validator supplies `model`, `api_base`, and `api_key`; the agent must use only those. In CI
and local development the same code path must run deterministically without a network. When a
model wraps JSON in prose or fenced blocks, `extract_json()` must pick the intended payload
reliably. Making that contract explicit lets reviewers check LLM-client changes against intent.

## User stories

1. **As the validator**, I know the agent honors managed-inference parameters and never calls
   third-party endpoints — so scoring is uniform and policy-compliant.
2. **As an agent developer**, I know offline mode returns caller-supplied stubs verbatim and
   how JSON is extracted from noisy model output — so I can test agent steps without a key.
3. **As a reviewer**, offline detection and `extract_json` tie-break rules are written down — so
   a change to `llm.py` is checked against the spec.

## Acceptance criteria (EARS)

### Managed-inference parameters

- `LLM(model, api_base, api_key, timeout)` SHALL store the validator-supplied `model`,
  `api_base` (trailing slash stripped), and `api_key` without substituting other credentials.
- WHEN `api_base` is missing or blank THE client SHALL enter offline mode.
- WHEN `api_key == "offline"` THE client SHALL enter offline mode.
- WHEN `VANGUARSTEW_OFFLINE=1` THE client SHALL enter offline mode regardless of other settings.

### Offline `chat()` behavior

- WHEN the client is offline THEN `chat(system, user)` SHALL NOT perform a network request.
- WHEN the client is offline THEN `chat()` SHALL return the JSON string `{"_offline": true}`.

### Offline `chat_json()` behavior

- WHEN the client is offline THEN `chat_json(system, user, stub=...)` SHALL NOT perform a
  network request.
- WHEN the client is offline and `stub` is provided THEN `chat_json()` SHALL return `stub`
  verbatim (no parsing or mutation).
- WHEN the client is offline and `stub` is `None` THEN `chat_json()` SHALL return `{}`.

### JSON extraction order

- `extract_json(text)` SHALL attempt parsing in this order:
  1. Valid JSON inside fenced code blocks (`` ```json ... ``` `` or `` ``` ... ``` ``).
  2. The raw response string verbatim via `json.loads`.
  3. Balanced top-level `{...}` / `[...]` spans scanned left-to-right (string literals inside
     JSON respected so nested brackets in values do not split spans).
- WHEN no step yields valid JSON THEN `extract_json()` SHALL raise `ValueError`.
- WHEN `text` is `None` THEN `extract_json()` SHALL raise `ValueError`.

### JSON candidate tie-breaking

- WHEN multiple fenced blocks parse successfully THE system SHALL pick the best candidate via
  `_pick_best_json`: prefer `dict` over `list`, then prefer the longest serialized form; WHEN
  two candidates have equal rank THE later candidate in the response SHALL win.
- WHEN multiple top-level spans parse successfully THE same tie-break rule SHALL apply.
- WHEN both a leading citation/array aside and a later object span parse successfully THE object
  span SHALL win (object rank beats array rank).

### Robustness (per constitution)

- Invalid fenced blocks and unbalanced bracket spans SHALL be skipped, not crash the extractor.
- Malformed JSON in one candidate SHALL NOT prevent trying other candidates.

## Out of scope

- **Codex / alternate backends** (`agent/codex_llm.py`) — a separate client with its own path.
- **Network transport errors** when online — raised to the caller; not part of this contract.
- Changing extraction tie-break behavior — code changes follow the SDD loop in their own PRs; this
  spec documents the as-built surface only.

## Verification

- `tests/test_spec_010_llm.py` (this PR) exercises each EARS block above against the real `LLM`
  class and `extract_json()` / `_pick_best_json()`.
- Broader unit coverage remains in `tests/test_smoke.py`.
