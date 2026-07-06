# Plan 011 — miner scored-surface manifest

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #726

How the [spec](./spec.md) maps onto `vanguarstew_agent_files.json` as-built. No new product code;
this records the contract surface so future manifest changes are reviewed against a plan.

## Architecture

```
vanguarstew_agent_files.json
  ├─ entrypoint: "agent.py"          → single importable module with solve()
  ├─ entrypoint_symbol: "solve"      → benchmark entry callable
  ├─ files: [ ... ]                  → scored / miner-editable paths
  └─ max_files: 32                   → hard cap on len(files)
```

## As-built scored surface (this repo)

| Path | Role |
| ---- | ---- |
| `agent.py` | orchestrates philosophy → plan → decide |
| `agent/__init__.py` | package marker |
| `agent/llm.py` | managed-inference client |
| `agent/context.py` | frozen context loader |
| `agent/philosophy.py` | step 1 — infer direction |
| `agent/planner.py` | step 3a — plan next actions |
| `agent/decider.py` | step 3b — concrete decision |

**Not scored:** `agent/review.py` (maintainer-assist CLI path), all of `benchmark/`, tests,
packaging, and this manifest itself.

## EARS → test mapping

| Spec section | Test group in `test_spec_011_manifest.py` |
| ------------ | ----------------------------------------- |
| Manifest document shape | `test_manifest_has_*`, `test_files_*` |
| On-disk presence and hygiene | `test_manifest_files_exist`, `test_no_duplicates`, `test_no_benchmark_paths`, `test_review_not_scored` |
| Entrypoint linkage | `test_entrypoint_defines_solve`, `test_manifest_includes_orchestration_modules` |
| File cap | `test_files_within_max_files_cap` |
| Robustness | `test_manifest_is_valid_json` |

## The invariants this pins

- **Bounded surface:** miners edit at most `max_files` declared paths.
- **Harness isolation:** benchmark code never appears in the editable list.
- **Stable entrypoint:** `agent.py::solve` remains the single seam named by the manifest.

## Verification strategy

`tests/test_spec_011_manifest.py` (this PR) maps one test group per EARS section. `solve()`
behavior is specified separately in [`specs/001-solve-contract`](../001-solve-contract/spec.md).

## Out of scope for this plan

Harness enforcement, changing manifest membership, and agent-step quality scoring.
