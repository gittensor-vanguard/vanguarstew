# Spec 001 — the `solve()` agent contract

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #466
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)

This spec makes the **existing, implicit** `solve()` contract explicit. It describes the
contract already implemented by `agent.py::solve` and required by `AGENTS.md`; it introduces
**no behavior change**. It is the reviewable contract the M5 subnet launch builds against.

## Why

`solve()` is the single seam between the validator's benchmark harness and a miner's agent.
Every miner edits the `agent/` package but must keep this seam stable, and the harness invokes
it identically across every frozen repo. An implicit contract drifts; an explicit one is
reviewable, testable, and safe to build a launch on.

## User stories

1. **As the validator**, I invoke one fixed function over a frozen repo and a managed-inference
   endpoint, and receive a structured maintainer decision I can score against revealed history —
   so scoring is uniform across agents and repos.
2. **As an agent developer / miner**, I implement freely inside `agent/` against a stable
   entrypoint and output shape — so my changes are scored, not broken by signature drift.
3. **As a reviewer**, I can check any agent change against a written contract at the SDD phase
   boundary — so intent doesn't drift between the spec and the code.

## Acceptance criteria (EARS)

### Entrypoint

- The system SHALL expose `solve(repo_path, request, model, api_base, api_key, n)` as the single
  agent entrypoint in `agent.py`.
- The system SHALL keep the `solve` signature stable; miners SHALL NOT change it (only the
  `agent/` implementation behind it).
- The system SHALL accept `model`, `api_base`, and `api_key` as managed-inference parameters and
  use no other inference endpoint or credentials.
- The system SHALL default `n` to 5 (the number of planned maintainer actions) and `request` to
  a maintainer-action prompt.

### Offline determinism

- WHEN `VANGUARSTEW_OFFLINE=1` (or `api_key == "offline"`, or no `api_base`) THE system SHALL use
  a deterministic offline stub for all inference, requiring no network.
- WHILE offline THE system SHALL still return a fully-shaped result (below), so the loop is
  exercisable in CI without a key.

### Output contract

- The system SHALL return a `dict` that includes at least the keys: `philosophy`, `plan`,
  `action`, `labels`, `reviewer`, `version_bump`, `patch`, `rationale`, `logs`, `steps`, `cost`,
  `success` (it MAY carry additional run-metadata keys, e.g. `_elapsed_s`).
- `philosophy` SHALL be the inferred repo direction; `plan` SHALL be a list of the next `n`
  maintainer actions; `action` SHALL be the concrete decided call.
- The system SHALL populate every declared key on every invocation (a field with no value is
  present as `null`/`[]`, never absent), so scorers read a stable shape.

### Robustness (per constitution)

- IF the LLM emits a malformed field (non-string where a string is expected, non-list where a
  list is expected) THEN `solve()` and the scoring pipeline SHALL coerce and log, not crash —
  per `AGENTS.md` → *Benchmark integrity*. One bad field SHALL NOT abort a replay run.

### Scoring surface

- The system SHALL treat only files listed in `vanguarstew_agent_files.json` as the scored agent
  surface; changes outside that manifest SHALL NOT affect an agent's score.

## Out of scope

- The managed-inference proxy / model hosting itself (validator-owned infrastructure).
- The benchmark harness internals — task generation, freeze, judge, and `score.py` scoring
  (specified by the revealed git history, not by this contract).
- The precise *quality* of the agent's decisions (that is what the benchmark measures; this spec
  fixes only the **shape and stability** of the seam).
- Any network access beyond the managed-inference endpoint.

## Verification

This contract is already exercised: `agent.py`'s `__main__` runs `solve()` offline, and the
existing suite (`tests/`) covers the pieces (`philosophy`, `planner`, `decider`, `review`) it
composes. A future task MAY add a `tests/test_solve_contract.py` asserting the output-shape and
offline-determinism criteria directly; this spec adds no code and does not require it.
