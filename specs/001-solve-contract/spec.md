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

## Inputs

The entrypoint signature is `solve(repo_path, request, model, api_base, api_key, n) → dict`.

| Param | Type | Default | Meaning |
| ----- | ---- | ------- | ------- |
| `repo_path` | `str` | `"/tmp/task_repo"` | Path to the repo frozen at T, with a `vanguarstew_context.json` file containing only knowable-at-T state |
| `request` | `str` | `"plan the next 5 maintainer actions"` | The maintainer decision being asked for |
| `model` | `str` | `"validator-managed-model"` | Managed-inference model identifier |
| `api_base` | `str` | `"http://validator-proxy/v1"` | Managed-inference endpoint URL |
| `api_key` | `str` | `"per-run-proxy-token"` | Managed-inference credential |
| `n` | `int` | `5` | Number of maintainer actions to plan |

The system SHALL accept `model`, `api_base`, and `api_key` as the only inference surface;
the agent SHALL NOT use any other endpoint, credential, or third-party key.

## Outputs

The system SHALL return a `dict` with every key below present on every invocation. A field
with no value SHALL be `null` (for scalars) or `[]` (for sequences), never absent.

| Key | Type | Optional | Source | Meaning |
| --- | ---- | -------- | ------ | ------- |
| `philosophy` | `dict` | no | `infer_philosophy()` | Inferred repo direction, values, and maintainer posture |
| `plan` | `list` | no | `plan_next_actions()` | The next `n` planned maintainer actions/PRs |
| `action` | `str \| null` | no | `decide()` | The concrete maintainer call — one of `merge`, `request-changes`, `reject`, `triage`, `release`, `patch`, `praise` |
| `labels` | `list` | no | `decide()` | Recommended labels for the triaged/merged item |
| `reviewer` | `str \| null` | no | `decide()` | Recommended reviewer handle, or `null` |
| `version_bump` | `str \| null` | no | `decide()` | Recommended version bump (`major`/`minor`/`patch`), or `null` |
| `patch` | `str \| null` | no | `decide()` | A unified diff when the action is `patch`, else `null` |
| `rationale` | `str` | no | `decide()` | The reasoning the pairwise judge evaluates |
| `logs` | `str` | no | — | Run-metadata summary of the executed steps |
| `steps` | `int` | no | — | Number of steps executed in the maintainer workflow |
| `cost` | `null` | no | — | Reserved for future cost tracking |
| `success` | `bool` | no | — | Whether the invocation completed without error |
| `_elapsed_s` | `float` | yes | — | Wall-clock seconds for the invocation (additional metadata) |

- The system SHALL populate every non-optional key on every invocation.
- The system MAY carry additional run-metadata keys (e.g. `_elapsed_s`); scorers SHALL ignore
  unrecognized keys.

## Offline mode

Offline mode is gated by three conditions checked in `agent/llm.py::LLM.__init__`:

- `VANGUARSTEW_OFFLINE=1` in the environment, **or**
- `api_key == "offline"` (the literal string), **or**
- `api_base` is falsy (empty, `None`, or whitespace-only)

WHEN any of these conditions is met, `LLM.offline` SHALL be `True` and:

- `LLM.chat()` SHALL return the deterministic stub `'{"_offline": true}'` without making a network call.
- `LLM.chat_json(system, user, stub=…)` SHALL return `stub` verbatim when offline (or `{}` when
  `stub` is `None`).

WHILE offline, `solve()` SHALL still invoke the full maintainer workflow (load context →
infer philosophy → plan → decide) and return a fully-shaped output dict, so the loop is
exercisable in CI without a network or a key.

## Errors

`solve()` SHALL NOT raise on malformed model output. Per the constitution's robustness
contract (`AGENTS.md` → Benchmark integrity):

- IF the LLM emits a malformed field (non-string where a string is expected, non-list where a
  list is expected), THEN `solve()` and the downstream scoring pipeline SHALL coerce and log a
  warning, not crash.
- One bad field SHALL NOT abort a replay run.

`solve()` MAY propagate exceptions from the filesystem (`OSError` on unreadable frozen repo) or
the inference transport (`urllib.error.URLError` / `http.client.HTTPException` on network
failure). These are infrastructure failures, not contract violations; the benchmark harness
(`benchmark/runner.py`) catches them.

## Out of scope

- The managed-inference proxy / model hosting itself (validator-owned infrastructure).
- The benchmark harness internals — task generation, freeze, judge, and `score.py` scoring
  (specified by the revealed git history, not by this contract).
- The precise *quality* of the agent's decisions (that is what the benchmark measures; this spec
  fixes only the **shape and stability** of the seam).
- Any network access beyond the managed-inference endpoint.

## Verification

- `tests/test_spec_001_solve.py` (this PR) exercises the entrypoint signature, offline
  output shape, and determinism criteria directly.
- Broader smoke coverage remains in `tests/test_smoke.py`; step-level contracts live in specs
  006–010.
