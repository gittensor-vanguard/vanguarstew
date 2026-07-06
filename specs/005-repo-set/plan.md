# Plan 005 — repo-set / curation contract

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #628

How the [spec](./spec.md) maps onto `benchmark/repo_set.py` as-built. No new product code; this
records the contract surface so future curation/loader changes are reviewed against a plan.

## Architecture

```
load_repo_set(path)                 # explicit path required; reads + parses JSON
  └─ validate_repo_set(data) -> RepoSet    (raises RepoSetError on any problem)
       ├─ strict top level: repos non-empty list; name/description/strategy optional str; else error
       └─ _validate_entry(raw, i, seen)    per repo
            ├─ name (non-empty, unique) · source (non-empty) · tier ∈ TIERS
            ├─ held_out bool · notes str · unknown keys -> error
            └─ _validate_freeze_window(fw)  # typed keys; ISO after/before; min_history≥1; after≤before
RepoSet(entries) → tuned() / held_out() / by_tier() / partition(which)
replay_kwargs(entry) → { recent_bias?, rotation_seed?, min_history?, after?, before? }  # for run_replay
```

## Data model

### Config (input)

| Level | Field | Rule |
| ----- | ----- | ---- |
| top | `repos` | required, non-empty list |
| top | `name`/`description`/`strategy` | optional strings; any other key → error |
| entry | `name` | required, non-empty, unique |
| entry | `source` | required, non-empty |
| entry | `tier` | one of `("recent","obscure")` |
| entry | `held_out` | bool (default False) |
| entry | `notes` | str |
| entry | `freeze_window` | object; keys ⊆ `{after,before,recent_bias,rotation_seed,min_history}` |

### `freeze_window` hint types

| Key | Type | Extra rule |
| --- | ---- | ---------- |
| `after` / `before` | str | non-empty; ISO `YYYY-MM-DD`; `after ≤ before` |
| `recent_bias` | bool | |
| `rotation_seed` | int | not bool |
| `min_history` | int | not bool; `≥ 1` |

## Contract surface (functions this spec pins)

`RepoSetError`, `RepoEntry`, `RepoSet` (`tuned`/`held_out`/`by_tier`/`partition`),
`validate_repo_set`, `load_repo_set`, `_validate_entry`, `_validate_freeze_window`,
`replay_kwargs`, `TIERS`, `_FREEZE_KEYS`.

## The invariants this pins

- **Fail-fast:** every malformed field is a load-time `RepoSetError` — never a silent zero-task drop.
- **Held-out isolation:** `held_out` entries are a separate generalization pass, not tuned.
- **Hint fidelity:** `replay_kwargs` forwards only present, validated hints to `run_replay`.

## Verification strategy

`tests/test_spec_005_repo_set.py` (this PR) exercises the strict-loading and freeze-window
validation paths plus the tuned/held-out split; broader behavior is in `tests/test_repo_set.py`.

## Out of scope for this plan

Changing any loader/curation behavior, the freeze/leakage path, or the curated repo contents.
Code changes follow the SDD loop in their own specs/PRs.
