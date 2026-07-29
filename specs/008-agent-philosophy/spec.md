# Spec 008 — agent philosophy inference

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #672
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`agent/philosophy.py`](../../agent/philosophy.py) (the module under test),
  [`agent/context.py`](../../agent/context.py) (`context_for_agent`, the render source),
  [`agent/llm.py`](../../agent/llm.py) (`chat_json`, Spec 010 — the offline-stub contract this
  module's determinism rests on), [`agent/planner.py`](../../agent/planner.py) (Spec 007) and
  [`agent/decider.py`](../../agent/decider.py) (Spec 006), the two consumers of the returned
  philosophy

This spec makes the **existing, implicit** philosophy-inference contract explicit. It describes the
as-built behavior of `agent/philosophy.py`; it introduces **no behavior change**.

## Why

Philosophy inference is step 1 of the agent loop and the grounding step for everything after it: the
planner and the decider both embed the returned dict in their prompts. It is not scored directly —
there is no labeled "correct philosophy" — so nothing downstream would catch it silently returning a
differently-shaped dict. Its two consumers index the documented keys, which makes the **shape**, not
the content, the load-bearing guarantee: every code path, including a non-dict context and an LLM
that returns something unusable, must produce the same five keys with the same field types.

`AGENTS.md` also requires that `VANGUARSTEW_OFFLINE=1` be deterministic and that a non-string field
from the LLM be coerced with a warning rather than crash the pipeline. This module is where both
land for step 1, and neither was written down.

## Field contract

The returned philosophy SHALL always be a dict with exactly these five keys:

| Key | Type | Meaning |
| --- | ---- | ------- |
| `summary` | `str` | one-sentence characterization of the project |
| `values` | `list[str]` | guiding values (`conservative`, `feature-first`, …) |
| `merge_bar` | `str` | what tends to get merged vs. rejected |
| `direction` | `str` | where the codebase appears to be heading |
| `evidence` | `list[str]` | concrete signals the inference used |

## Constants

- `_OFFLINE_STUB` SHALL carry exactly those five keys, with
  `summary = "offline stub philosophy"`, `values = []`, `merge_bar = "unknown (offline)"`,
  `direction = "unknown (offline)"`, `evidence = []`.
- `SYSTEM` SHALL instruct the model to infer values, risk tolerance and direction, to be
  evidence-based, and to respond **only** with JSON.
- `FEWSHOT` SHALL carry two contrasting worked examples (one conservative library, one fast-moving
  app) whose `OUTPUT:` payloads are each valid JSON carrying all five keys — contrasting on purpose,
  so the examples demonstrate the shape and the specificity bar without anchoring the model to a
  verdict.

## Acceptance criteria (EARS)

### Text-field normalization (`_normalize_text`)

- WHEN `value` is `None` THEN `_normalize_text(value, default)` SHALL return `default` (the
  **None-text fallback**; the parameter defaults to `""`).
- WHEN `value` is a `str` THEN it SHALL be returned **verbatim** — not stripped, and an empty string
  `""` SHALL be returned as `""` rather than falling back to `default`. Only `None` triggers the
  fallback.
- OTHERWISE it SHALL return `str(value)` — the **non-string coercion**: `5` → `"5"`, `0` → `"0"`,
  `False` → `"False"`, `["a"]` → `"['a']"`, `{"k": 1}` → `"{'k': 1}"`. No type is rejected and none
  raises.

### List-field normalization (`_normalize_string_list`)

- WHEN `value` is `None` THEN it SHALL return `[]`.
- WHEN `value` is a `str` THEN it SHALL be **wrapped**, stripped, as a single-item list —
  `"  perf-first  "` → `["perf-first"]` — and a blank/whitespace-only string SHALL yield `[]`. A
  bare string is a common LLM shape for a one-element list and is accepted rather than dropped.
- WHEN `value` is a `list` THEN each item SHALL be handled in order: a `None` item is **skipped**;
  every other item becomes `str(item).strip()` and is **skipped when the result is blank**. So
  `[None, "", "  ", " a "]` → `["a"]`, while falsy non-`None` scalars survive their coercion
  (`0` → `"0"`, `False` → `"False"`) because their string form is not blank. Nested containers are
  stringified (`["n"]` → `"['n']"`), never flattened.
- OTHERWISE (a `dict`, a number, a bool) it SHALL return `[]` — a non-list, non-str container is not
  a list of values and is dropped rather than stringified into one.

### Philosophy mapping (`_normalize_philosophy`)

- WHEN `out` is not a dict (the **non-dict LLM payload** — a list, a string, a number, `None`) THEN
  it SHALL return `dict(stub)` and SHALL NOT raise.
- OTHERWISE it SHALL return exactly the five documented keys: `summary`, `merge_bar` and `direction`
  through `_normalize_text` with the corresponding `stub` value as the default, and `values` /
  `evidence` through `_normalize_string_list`.
- Consequences that are part of the contract: a **missing or `None`** text field falls back to the
  stub's value, while a missing list field yields `[]` (the stub is never consulted for a list); and
  any **extra** key the model emits SHALL be dropped, so the output shape cannot grow from model
  output.
- `dict(stub)` is a **shallow** copy: the returned `values` and `evidence` are the *same list
  objects* as the stub's. A caller that mutates them in place therefore mutates `_OFFLINE_STUB` and
  every later fallback result. Callers SHALL treat the returned lists as read-only.

### Inference (`infer_philosophy`)

- WHEN `context` is not a dict (`None`, a string, a number, a list, a bool — the **non-dict context
  fallback**) THEN it SHALL return `dict(_OFFLINE_STUB)` **without calling the LLM at all**.
- OTHERWISE it SHALL call `llm.chat_json(SYSTEM, user, stub=_OFFLINE_STUB)` exactly once and return
  `_normalize_philosophy(out, _OFFLINE_STUB)`, so an unusable payload still yields the documented
  five keys.
- The `user` prompt SHALL contain, in order: the instruction to infer from this repository state,
  the full `FEWSHOT` block, an instruction to base every field on this repository's own signals
  rather than the examples, the rendered context, and the enumeration of the five requested keys.

### Offline determinism

- WHEN `VANGUARSTEW_OFFLINE=1` (or no API key is configured) THEN `agent/llm.py`'s `chat_json`
  returns the `stub` argument verbatim without a network call, so `infer_philosophy` SHALL return
  the normalized `_OFFLINE_STUB` — `{"summary": "offline stub philosophy", "values": [],
  "merge_bar": "unknown (offline)", "direction": "unknown (offline)", "evidence": []}`.
- That result SHALL be **byte-identical across repeated calls** and **independent of the context
  contents**: two offline calls with different dict contexts SHALL return equal dicts. This is the
  `AGENTS.md` M0 requirement ("WHEN `VANGUARSTEW_OFFLINE=1` THE system SHALL use a deterministic
  offline stub") as it applies to step 1, and it is what makes an offline replay reproducible.
- The offline path SHALL return a **fresh top-level dict** on each call, so reassigning a key on one
  result does not affect another (the shared-list caveat above still applies to in-place mutation).

### Rendering (`_render`)

- `_render(context)` SHALL pass `context` through `context_for_agent` (the leakage-scrubbed agent
  view) and then keep exactly the whitelist `frozen_at`, `recent_commits`, `open_issues`,
  `open_prs`, `labels`, `milestones`, `releases`, `readme_excerpt` — in that order, with a missing
  key rendered as `null` — serialized with `json.dumps(..., indent=1)`.
- The serialization SHALL be truncated to **12000 characters**. A context that exceeds the cap is
  cut mid-value, so the rendered block is not necessarily valid JSON; the cap is a prompt-budget
  bound, not a serialization guarantee.

## Out of scope

- `context_for_agent`'s own scrubbing rules (Spec 003) and `chat_json`'s transport behavior
  (Spec 010).
- The philosophy's *content* quality — there is no ground truth for it, by design.
- Correcting any of the caveats documented above (the shared stub lists, the truncation); each is a
  behavior change and belongs in its own issue.

## Verification

- `tests/test_spec_008_philosophy.py` exercises each EARS block above, pinning **literal** expected
  values rather than re-deriving them from the module.
- Broader behavioral coverage remains in `tests/test_philosophy.py`.
