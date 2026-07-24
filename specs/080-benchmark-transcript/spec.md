# Spec 080 — run transcript

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1990
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/transcript.py`](../../benchmark/transcript.py) (the module under test),
  [`benchmark/attestation.py`](../../benchmark/attestation.py) (binds `digest` into a quote's
  `report_data`, Spec 075), [`benchmark/runner.py`](../../benchmark/runner.py) (the replay the
  transcript records), [`agent/llm.py`](../../agent/llm.py) (the chat-completion request shape the
  key is built from)

This spec makes the **existing, implicit** transcript contract explicit. It describes the as-built
behavior of `benchmark/transcript.py`; it introduces **no behavior change**.

## Why

Every other input to a replay run is already pinned — the repo is frozen at commit T, the task RNG
is seeded, the judge's dual-order rotation is seeded. The model call is not: two runs of identical
inputs can diverge purely because a hosted model answered differently. A transcript turns the model
into an *input* — record once, then anyone can replay the same run offline and get byte-identical
output. That is what makes an attestation quote worth anything: without reproducibility nobody can
independently re-derive the artifact the quote attests.

Two properties carry that weight, and both are currently undocumented: replay is **ordered** (the
dual-order judge asks the same pair twice, so responses are a list per key served in recorded
order), and keys are **byte-stable** (built from a canonical form of only the semantically relevant
request fields, so they do not shift on dict ordering or on an unrelated transport field). This spec
writes both down, along with the tolerance rules for an untrusted transcript file and the places
where the as-built behavior is narrower than the docstrings claim (#1990).

## User stories

1. **As a verifier**, I can load a recorded transcript and replay a run offline, getting the
   original answers back in the original sequence.
2. **As an attestation consumer**, I can rely on `canonical_json`/`digest` being byte-stable for the
   JSON-representable values a run actually produces, and I can see written down where that
   guarantee stops.
3. **As a reviewer**, every miss / exhaustion / non-dict / malformed-file / unkeyed-row branch is
   written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `TRANSCRIPT_VERSION` SHALL be `1`.
- `_KEYED_REQUEST_FIELDS` SHALL be `("model", "messages", "temperature")`.

## Acceptance criteria (EARS)

### Canonical serialization (`canonical_json`)

- `canonical_json(value)` SHALL be `json.dumps` with `sort_keys=True`,
  `separators=(",", ":")`, `ensure_ascii=True`, `default=str`. Concretely: `{"b": 1, "a": 2}` SHALL
  serialize to `{"a":2,"b":1}` (key order comes from sorting, not insertion), `{"k": "café"}` to
  `{"k":"café"}`, and `[1, {"x": 2}]` to `[1,{"x":2}]` (no incidental whitespace).
- IF a value is not JSON-serializable THEN `default=str` SHALL stringify it rather than raising.
  **The stability guarantee does not survive that fallback**, and the boundary is part of the
  contract: two *distinct* objects whose `str()` agree SHALL produce the **same** serialization (and
  therefore the same key and digest), and a value whose `str()` embeds a process-local identity
  (`<object object at 0x…>`) SHALL produce a serialization that differs between objects and is not
  reproducible across processes. Callers that need a stable digest SHALL pass JSON-representable
  values.

### Digest primitive (`digest`)

- `digest(value)` SHALL be the hex `sha256` of `canonical_json(value)` encoded UTF-8, and SHALL
  therefore be stable for equal canonical forms. Pinned literals: `digest({})` SHALL be
  `44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a` and `digest(None)` SHALL be
  `74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b`.
- `digest({"a": 1, "b": 2})` SHALL equal `digest({"b": 2, "a": 1})` (insertion order is not
  observable).

### Replay key (`request_key`)

- WHEN `request` is a dict THEN `request_key(request)` SHALL be
  `digest({field: request.get(field) for field in _KEYED_REQUEST_FIELDS})` — i.e. built **only** from
  the keyed fields.
- Consequences that are part of the contract: adding transport/bookkeeping fields (`stream`, `user`,
  `n`, …) SHALL NOT change the key; changing `model`, `messages` or `temperature` SHALL change it;
  and an **absent** keyed field SHALL key identically to that field present and `None` (`.get`
  defaults to `None`).
- OTHERWISE (a non-dict request) it SHALL log a warning naming the type and return `digest(request)`
  of the whole value, rather than raising — an unmatchable key simply misses on replay, which the
  caller already handles.

### Construction (`TranscriptStore.__init__`)

- `TranscriptStore(entries)` SHALL store `list(entries or [])`, so `None` and any falsy `entries`
  yield an empty store. The constructor is **not** the tolerant path: a truthy non-iterable
  (e.g. `5`) SHALL raise `TypeError`. `from_dict` is the entry point for untrusted data.

### Recording (`record`)

- `record(request, response)` SHALL append `{"key": request_key(request), "request": request if
  isinstance(request, dict) else None, "response": response}` and SHALL NOT return a value.
- The stored `request` SHALL be the caller's object itself, not a copy. IF the caller mutates it
  after recording THEN the stored body SHALL change while `key` stays computed from the value at
  record time, so `request_key(entry["request"])` no longer equals `entry["key"]`.
- WHEN the request is not a dict THEN the stored body SHALL be `None` while the key stays
  `digest(request)`, so that entry's key likewise SHALL NOT be recomputable from the stored body.
  In both cases the stored bodies are auditability aids, not a verified index.

### Ordered replay (`replay`)

- `replay(request)` SHALL select the entries whose `key` equals `request_key(request)`, in recorded
  order, and return the `response` at the per-key cursor, advancing it by one.
- WHEN no entry matches THEN it SHALL return `None` **without** warning (an ordinary miss).
- WHEN the cursor has passed the last recorded match THEN it SHALL log a warning naming the count
  and the key's first 12 characters, and return `None` — a miss, never a wrong answer.
- A matched entry with no `response` key SHALL yield `None` via `.get`, and a row whose `key` is
  absent SHALL never match (a `None` key cannot equal a hex digest).
- `reset()` SHALL clear all cursors so the same store can drive another run from the start; it SHALL
  NOT drop, reorder, or otherwise touch the entries.

### Size and serialization (`__len__`, `to_dict`, `save`, `load`)

- `len(store)` SHALL be the number of entries, including entries that can never be replayed.
- `to_dict()` SHALL be exactly `{"version": TRANSCRIPT_VERSION, "entries": <the entries>}`.
- `save(path)` SHALL write `to_dict()` as UTF-8 JSON with `indent=1, sort_keys=True` (a readable
  file, deliberately not the `canonical_json` form), and `load(path)` SHALL be
  `from_dict(json.load(...))`, so a save/load round trip preserves replay behavior.

### Tolerant load (`from_dict`)

- WHEN `data` is not a dict THEN it SHALL log a warning naming the type and return an empty store.
- WHEN `entries` is not a list AND is not `None` THEN it SHALL log a warning naming the type and
  return an empty store. WHEN `entries` is `None` or absent THEN it SHALL return an empty store
  **silently** (no warning).
- OTHERWISE it SHALL keep the rows that are dicts and drop the rest **without** a per-row warning.
  Row *contents* SHALL NOT be validated: a `{}` row is kept, is permanently unreplayable, and still
  counts toward `len()` and `digest()`.
- `version` SHALL NOT be read, validated, or reported. A transcript declaring a newer `version`
  SHALL load as if it were `TRANSCRIPT_VERSION` and SHALL be re-stamped `TRANSCRIPT_VERSION` by the
  next `to_dict()`/`save()`.

### Transcript identity (`TranscriptStore.digest`)

- `store.digest()` SHALL be `digest([[entry.get("key"), entry.get("response")] for entry in
  entries])` — keys and responses only, in order.
- Consequences that are part of the contract: the identity SHALL be unchanged by a cosmetic change
  to a stored request body (bodies are derived data), SHALL change when the recorded order changes,
  and SHALL change when an unreplayable row (e.g. `{}`, contributing `[None, None]`) is present.

### Pure evaluation

- Apart from `save`/`load`, the module SHALL perform no I/O and SHALL make no network calls.
- `replay` SHALL NOT mutate the entries and SHALL NOT mutate the request it is given.

## Out of scope

- `benchmark/attestation.py`'s evidence binding (Spec 075) and the replay proxy that wires a store
  into `agent/llm.py`.
- Changing any of the divergences catalogued above; this spec documents them, and any correction is
  a separate behavior-change issue.

## Verification

- `tests/test_spec_080_transcript.py` exercises each EARS block above, pinning **literal** expected
  values (exact serializations and exact `sha256` hexes) rather than re-deriving them from the
  module, so a refactor that changes the canonical form fails loudly.
- Broader behavioral coverage remains in `tests/test_transcript.py`.
