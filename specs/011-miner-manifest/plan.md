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

**Not scored, but imported by scored code:** `agent/decider.py` reads
`benchmark.score.base_from_releases`. That import crosses into harness code, but the *check* in
this plan only follows `agent.*` imports — it correctly stops there rather than pulling
`benchmark/` into the editable surface.

## EARS → test mapping

| Spec section | Test group in `test_spec_011_manifest.py` |
| ------------ | ------------------------------------------ |
| Manifest document shape | `test_manifest_is_valid_json_object`, `test_manifest_matches_schema` |
| On-disk presence and hygiene | `test_manifest_files_exist_on_disk`, `test_manifest_files_have_no_duplicates` |
| Scored-surface confinement | `test_manifest_files_are_confined_to_agent_surface`, `test_review_module_is_not_part_of_scored_surface` |
| Entrypoint linkage | `test_entrypoint_defines_declared_symbol`, `test_manifest_includes_full_agent_import_graph` |
| File cap | `test_files_within_max_files_cap` |
| Robustness | `test_manifest_json_reloads_without_error` |

## The invariants this pins

- **Bounded surface:** miners edit at most `max_files` declared paths.
- **Harness isolation, by construction:** any path outside `entrypoint` + `agent/` fails the
  confinement check, so a future stray `benchmark/`, `scripts/`, or `specs/` entry is caught
  without needing to enumerate every non-agent directory.
- **Stable entrypoint:** `agent.py::solve` remains the single seam named by the manifest, and
  the modules it actually depends on (derived by parsing imports, not maintained by hand) must
  all be listed.

## Verification strategy

`tests/test_spec_011_manifest.py` (this PR) maps one test group per EARS section above. The
entrypoint-linkage check walks `agent.py`'s real `ast` import graph — a manifest that omits a
module `agent.py` newly depends on fails the test immediately, instead of silently drifting from
what miners are actually allowed to touch. `solve()` behavior itself is specified separately in
[`specs/001-solve-contract`](../001-solve-contract/spec.md).

## Out of scope for this plan

Harness enforcement, changing manifest membership, and agent-step quality scoring.
