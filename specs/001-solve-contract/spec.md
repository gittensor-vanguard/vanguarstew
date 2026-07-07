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

`agent.py::solve` (ground truth) declares six keyword-assignable parameters, all with
defaults, so the harness may invoke it with any subset:

| Parameter  | Type  | Default                                | Meaning |
|------------|-------|----------------------------------------|---------|
| `repo_path`| `str` | `"/tmp/task_repo"`                     | Path to the frozen checkout at T. The frozen context is read from `.vanguarstew_context.json` inside it; when that file is absent or unreadable, context is rebuilt from git alone (see `agent/context.py`). |
| `request`  | `str` | `"plan the next 5 maintainer actions"` | Free-text decision request, forwarded verbatim to the decider (step 3b). |
| `model`    | `str` | `"validator-managed-model"`            | Managed-inference model id, forwarded unmodified to the `LLM` client. |
| `api_base` | `str` | `"http://validator-proxy/v1"`          | OpenAI-compatible endpoint root (trailing slash stripped). Empty/missing ⇒ offline mode. |
| `api_key`  | `str` | `"per-run-proxy-token"`                | Per-run bearer token. The literal `"offline"` ⇒ offline mode. |
| `n`        | `int` | `5`                                    | Plan length: the returned `plan` carries at most `n` items. |

- The system SHALL accept exactly these six parameters with these defaults; the signature is
  the stable seam and SHALL NOT change (see *Entrypoint* above).
- The system SHALL forward `model` / `api_base` / `api_key` to the LLM client unmodified and
  SHALL use no other endpoint or credentials (contract detail in
  [`specs/010-agent-llm`](../010-agent-llm/spec.md)).

## Outputs

`solve()` SHALL return a `dict` carrying all twelve declared keys on every invocation — a
field with no value is present as `null` / `[]` / `""`, never absent:

| Key            | Type                                    | Notes |
|----------------|-----------------------------------------|-------|
| `philosophy`   | `dict`                                  | Normalized to the keys `summary` (`str`), `values` (`list`), `merge_bar`, `direction`, `evidence` (`list`); stub-shaped offline. |
| `plan`         | `list[dict]`, length ≤ `n`              | Each item carries `title` (`str`), `kind` (one of `feature`, `bugfix`, `refactor`, `docs`, `release`, `dep`, `triage`), `rationale` (`str`), `theme` (`str`); items MAY also carry `files` (`list[str]`) and, when queue reconciliation matched an open PR, `restates_pr` (`int` or `null`). |
| `action`       | `str`                                   | Always one of the ten `VALID_ACTIONS` (`merge`, `request-changes`, `reject`, `triage`, `assign-reviewer`, `release`, `plan`, `patch`, `close`, `label`). Known synonyms are normalized (`"approve"` → `"merge"`); anything outside the vocabulary falls back to `"plan"` — the objective scorer must never see free text here. |
| `labels`       | `list[str]`                             | `[]` when not triaging; never `null`. |
| `reviewer`     | `str` or `null`                         | Blank/whitespace coerces to `null`. |
| `version_bump` | `"major"` / `"minor"` / `"patch"` / `null` | Case- and synonym-normalized (`"None"`, `"n/a"` → `null`), matching `benchmark.score._norm_bump`. |
| `patch`        | `str` or `null`                         | A unified git diff when `action == "patch"`; whitespace-only coerces to `null`. |
| `rationale`    | `str`                                   | Never `null`; `""` when the model gave none. |
| `logs`         | `str`                                   | Short step trace, e.g. `"philosophy+plan(3)+decision"`. |
| `steps`        | `int`                                   | The fixed pipeline depth (`3`: philosophy → plan → decision). |
| `cost`         | `null` (reserved)                       | Consumers SHALL tolerate a number here. |
| `success`      | `bool`                                  | `True` for a completed run. |

- The system MAY add underscore-prefixed run-metadata keys (e.g. `_elapsed_s`, a `float`);
  consumers SHALL ignore metadata keys they do not recognize, and determinism comparisons
  SHALL exclude them.

## Errors

- WHEN offline, `solve()` SHALL complete without raising for a readable frozen checkout — no
  network is touched and every inference step returns a deterministic stub.
- IF the managed endpoint is unreachable, times out, or answers with an HTTP error THEN the
  transport exception (`urllib.error.URLError` / `HTTPError`, `OSError` including socket
  timeouts) SHALL propagate to the harness: a transport failure is not a scoreable outcome
  and MUST NOT be silently converted into one.
- IF the model emits unparsable JSON or a malformed chat-completion envelope THEN `solve()`
  SHALL NOT raise: every step calls `chat_json` with a deterministic stub and falls back to
  it (M4 — *no agent crashes from malformed LLM output*).
- IF the frozen context file is absent, unreadable, corrupt JSON, or a non-object THEN
  `solve()` SHALL NOT raise: context is rebuilt from git, and malformed fields inside a
  loaded context are coerced and logged (see *Robustness* above).
- `solve()` declares no domain-specific exception types of its own.

## Offline mode

- The system SHALL enter offline mode when ANY of: `VANGUARSTEW_OFFLINE=1` is set in the
  environment, `api_key == "offline"`, or `api_base` is empty/missing.
- WHILE offline, `LLM.chat()` SHALL return the literal JSON string `{"_offline": true}` and
  `LLM.chat_json()` SHALL return the caller's stub verbatim, with no network request.
- WHILE offline, the three steps SHALL produce their deterministic stubs: philosophy
  `{"summary": "offline stub philosophy", "values": [], "merge_bar"/"direction":
  "unknown (offline)", "evidence": []}`; a plan that prioritizes reviewing the visible open-PR
  queue (else a single `triage` item), reconciled and capped to `n`; and a decision of
  `action: "plan"` with `labels: []`, `reviewer`/`version_bump`/`patch` `null`, rationale
  `"offline stub decision"`.
- WHILE offline, two invocations over the same frozen checkout SHALL return identical results
  apart from underscore-prefixed run metadata.
- The offline path SHALL exercise the full pipeline shape (all *Outputs* keys populated), so
  CI validates the contract without a key — verified by `tests/test_spec_001_solve.py`.

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
