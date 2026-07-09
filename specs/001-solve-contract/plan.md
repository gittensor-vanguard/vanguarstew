# Plan 001 — `solve()` agent contract

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #466

How the [spec](./spec.md) maps onto the code that already implements it. No new code is proposed
here; this records the architecture and data shapes so future agent changes are reviewed against
a written plan.

## Architecture

`solve()` (in `agent.py`) is a thin, fixed orchestration over the miner-editable `agent/`
package. It runs the maintainer workflow in order and assembles the output contract:

```
solve(repo_path, request, model, api_base, api_key, n)
  └─ LLM(model, api_base, api_key)          # agent/llm.py — managed-inference client; offline stub
  └─ load_context(repo_path)                # agent/context.py — knowable-at-T frozen context
  └─ infer_philosophy(context, llm)         # agent/philosophy.py — step 1: repo direction
  └─ plan_next_actions(context, philosophy, n, llm)  # agent/planner.py — step 3a: next N actions
  └─ decide(context, philosophy, request, llm)       # agent/decider.py — step 3b: concrete call
  → assemble the output dict (spec §Output contract)
```

Only `agent.py` + the `agent/` package are editable/scored (per `vanguarstew_agent_files.json`);
everything under `benchmark/` is validator-owned and out of this contract's scope.

## Data model

### Input

| Param | Type | Meaning |
| ----- | ---- | ------- |
| `repo_path` | `str` | path to the repo **frozen at T** (`+ .vanguarstew_context.json`) — only knowable-at-T state |
| `request` | `str` | the maintainer decision being asked for |
| `model` / `api_base` / `api_key` | `str` | managed-inference endpoint + credentials (the only inference surface) |
| `n` | `int` | number of maintainer actions to plan (default 5) |

### Output (the scored object)

| Key | Type | Source |
| --- | ---- | ------ |
| `philosophy` | `dict` | `infer_philosophy` — inferred repo direction/values |
| `plan` | `list` | `plan_next_actions` — the next `n` actions/PRs |
| `action` | `str \| null` | `decide` — the concrete maintainer call (merge/triage/release/patch/…) |
| `labels` / `reviewer` / `version_bump` | list / str / str | `decide` — decision metadata |
| `patch` | `str \| null` | `decide` — a unified diff when the action is a patch |
| `rationale` | `str` | `decide` — the reasoning the pairwise judge evaluates |
| `logs` / `steps` / `cost` / `success` | str / int / — / bool | run metadata |

Every key is always present (spec §Output contract); a missing value is `null` / `[]`.

## Contracts this depends on

- **LLM contract** (`agent/llm.py`): `chat_json(system, user, stub=…)` returns parsed JSON, and
  **returns `stub` verbatim when offline** — the basis for the offline-determinism criteria.
- **Context contract** (`agent/context.py`): the loaded context is knowable-at-T only; nothing
  created/published after T leaks in (enforced by `benchmark/` freeze + leakage, out of scope
  here but relied on).
- **Robustness contract** (`AGENTS.md` → Benchmark integrity): downstream helpers coerce
  malformed LLM fields rather than crash, so one bad field never aborts a replay.

## Verification strategy

- `agent.py __main__` runs `solve()` offline end-to-end.
- Unit suites already cover each composed step (`tests/test_planner.py`, `test_decider.py`,
  `test_review.py`, …).
- Optional follow-up task: `tests/test_solve_contract.py` asserting the output-shape and
  offline-determinism criteria directly. Tracked separately; not part of this docs-only change.

## Out of scope for this plan

Regenerating or changing any `agent/` behavior. This plan documents the contract as-built; code
changes against it follow the SDD loop (Tasks → Implement) in their own specs/PRs.
