# Spec 006 — the agent decision contract (`decide()`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #629
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)* / *Benchmark integrity*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (`decide()`'s output is the `action`/`patch`/… of `solve()`)

This spec makes the **existing, implicit** decision contract explicit. It describes the as-built
behavior of `agent/decider.py::decide()`; it introduces **no behavior change**. `decide()` is the
agent's most consequential internal step — it produces the concrete maintainer call that both the
objective anchor and the decision-process judge score, so its output shape and its tolerance of
malformed model output must be pinned down.

## Why

The model's raw JSON is untrusted: an `action` may arrive as a synonym, a wrong type, or garbage;
`labels` may be a bare string; `version_bump` may be miscased. If any of that reached the scorer
unnormalized, a real decision would be misread or the run would crash. `decide()` therefore
coerces every field onto a documented contract — which must be written down and verified.

## User stories

1. **As the validator**, `decide()` always returns a fixed-shape decision with canonical field
   types — so scoring reads a stable object regardless of model noise.
2. **As an agent developer**, I know exactly which `action` values are canonical and how fields
   are coerced — so I target real maintainer decisions, not format guessing.
3. **As a reviewer**, the decision contract and its normalization are written down — so changes to
   `decider.py` are checked against them.

## Acceptance criteria (EARS)

### Output shape

- `decide(context, philosophy, request, llm)` SHALL return a `dict` in which the six documented
  keys `action`, `labels`, `reviewer`, `version_bump`, `patch`, `rationale` are always present
  and normalized (below). These six are the scored decision surface. Any additional keys the
  model emits pass through unchanged (they are not part of the contract and are not normalized) —
  a documented, accepted behavior, not a guarantee of exactly-six keys.
- WHEN the model returns a non-dict (or offline) THE result SHALL be the deterministic stub
  (`action="plan"`, `labels=[]`, `reviewer=None`, `version_bump=None`, `patch=None`,
  `rationale="offline stub decision"`), then normalized — every key always present.

### Field normalization

- `action` SHALL be mapped onto `VALID_ACTIONS` (`merge`, `request-changes`, `reject`, `triage`,
  `assign-reviewer`, `release`, `plan`, `patch`, `close`, `label`) via an exact match or a known
  synonym (e.g. `assign_reviewer`/`assign reviewer` → `assign-reviewer`); a non-string or
  unrecognized `action` SHALL default to `plan` (and log), never crash.
- `labels` SHALL be coerced to `list[str]` — a bare string becomes a single-element list, a list
  drops blank/`None` entries and stringifies the rest, anything else becomes `[]`.
- `reviewer` SHALL be coerced to `str | None` (blank → `None`).
- `version_bump` SHALL be one of `major`/`minor`/`patch` or `None` — case-insensitively, with
  null-ish/unknown values → `None`, matching the scoring contract (`benchmark.score._norm_bump`)
  so a valid release prediction isn't dropped over case/synonym noise.
- `patch` SHALL be coerced to `str | None` (blank → `None`); `rationale` SHALL be coerced to a
  string (never `None`) — it is the text the decision-process judge evaluates.

### Robustness (per constitution)

- IF any field arrives as a malformed type THEN `decide()` SHALL coerce it as above and continue —
  never raise — per `AGENTS.md` → *Benchmark integrity*.

## Out of scope

- The **planner** and **philosophy** steps of `solve()` (their own contracts), and the
  maintainer-**review** path (`agent/review.py`, a separate output).
- The *quality* of the decision (that is what the judge + anchor measure) — this spec fixes only
  the shape and normalization of the decision object.

## Verification

Ships `tests/test_spec_006_decision.py`, asserting the criteria against the code: action
synonym/non-string/unknown → canonical or `plan`; `labels` coercion from string/list/junk;
`reviewer` and `patch` blank → `None`; `version_bump` case-folding and null-ish/unknown → `None`;
and an end-to-end `decide()` over a fake LLM returning malformed fields yields the full normalized
shape. Complements `tests/test_decider.py`. The spec changes no product code.
