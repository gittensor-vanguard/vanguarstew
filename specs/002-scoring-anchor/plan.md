# Plan 002 — objective scoring anchor

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #494

How the [spec](./spec.md) maps onto `benchmark/score.py` as-built. No new code is proposed; this
records the contract surface and data shapes so future scoring changes are reviewed against a
written plan.

## Architecture

```
composite_score(winner, objective, w_judge, w_objective)   # final blended score in [0,1]
  ├─ _JUDGE_OUTCOME[winner]              # A=1.0 / tie=0.5 / B=0.0  (the pairwise judge, out of scope)
  └─ objective_component(objective)      # the scalar anchor
        └─ objective_score(plan, revealed, version_bump, base_version, open_issues)
             ├─ module_recall(plan, revealed)            # + weighted_module_recall, module_weights
             ├─ kind_recall(plan, revealed)              # via commit_kind / plan_kind
             ├─ backlog_recall(plan, revealed, open_issues)   # DIAGNOSTIC ONLY (excluded from scalar, #148)
             ├─ release_signaled / release_predicted → release_match
             └─ bump_actual (bump_level over base_version→released_version) vs version_bump → bump_match
```

`objective_score` **composes** all fields (for inspection); `objective_component` **collapses**
only the ranking-relevant subset (`_objective_for_component` / `_COMPONENT_SCORE_KEYS`) into the
scalar — the diagnostic/scalar boundary is the key invariant (#148).

## Data model

### Input

| Param | Type | Meaning |
| ----- | ---- | ------- |
| `plan` | `list[dict]` | the agent's planned actions (`title`/`theme`/`kind`) |
| `revealed` | `list[dict]` | the revealed commit window (`subject`, `files`) — structural ground truth |
| `version_bump` | `str \| None` | the agent's predicted bump level |
| `base_version` | `str \| None` | version at freeze T (e.g. latest frozen release tag, via `base_from_releases`) |
| `open_issues` | `list \| None` | backlog issues knowable at T (optional; diagnostic only) |

### Output (`objective_score` dict)

| Field | Feeds scalar? | Source |
| ----- | ------------- | ------ |
| `module_recall` / `weighted_module_recall` / `module_weights` | ✅ (weighted preferred) | `module_recall` |
| `release_signaled` / `release_predicted` / `release_match` | ✅ (only when signaled) | `release_*` |
| `bump_actual` / `bump_predicted` / `bump_match` | ✅ (only when `bump_actual` is not None) | `bump_level` |
| `kind_recall` (+ diagnostics) | reported | `kind_recall` |
| `backlog_recall` (+ addressed/matched issue numbers) | ❌ diagnostic only (#148) | `backlog_recall` |

## Contract surface (functions this spec pins)

`objective_score`, `objective_component`, `composite_score`, `module_recall`, `changed_modules`,
`is_release_subject`, `release_signaled`, `release_predicted`, `released_version`, `bump_level`,
`base_from_releases`, `commit_kind`, `plan_kind`, `kind_recall`, `backlog_recall`. The lexical
`trajectory_overlap` is explicitly **not** part of the ranking contract.

## Verification strategy

Deterministic + offline. Covered by `tests/test_score.py` and `tests/test_compose.py`
(including the invariant that backlog recall never shifts the scalar). A future task MAY add a
contract-level test asserting the diagnostic/scalar boundary directly; tracked separately, not
part of this docs-only change.

## Out of scope for this plan

Changing any scoring behavior, weights, or the judge. Code changes against this contract follow
the SDD loop (Tasks → Implement) in their own specs/PRs.
