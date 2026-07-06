# Plan 024 — freeze digest (`freeze_digest`)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #858

How the [spec](./spec.md) maps onto `benchmark/freeze_digest.py` as-built. No new product code;
this records the contract surface so future changes are reviewed against a plan.

## Architecture

```
freeze_digest(artifact) -> {kind, entries, count}
  ├─ artifact = _dict(artifact)                     # non-dict -> {}
  ├─ kind = artifact_kind(artifact)                 # comparability: single/multi/generalization/invalid
  ├─ rows = _collect_rows(artifact)                 # [(partition, row_dict), ...]
  │     generalization -> tuned.per_repo + held_out.per_repo   (partition = tuned/held_out)
  │     multi          -> per_repo                              (partition = multi)
  │     single/invalid -> []
  │     (each via _rows_from_per_repo: non-list -> [] logged; non-dict row -> skipped)
  ├─ entries = [{partition, repo:_repo_key(row), freeze_commit:_freeze_commit(row)} for ...]
  ├─ entries.sort(key=(partition, repo, freeze_commit or ""))
  └─ return {kind, entries, count: len(entries)}
freeze_digest_headline(summary) -> "freeze digest: {kind} with {count} entr(y|ies)"
```

## Data model

### Input

`artifact`: a replay artifact dict (single / multi / generalization shaped); malformed tolerated.

### Output

| Key | Meaning |
| --- | ------- |
| `kind` | `single` / `multi` / `generalization` / `invalid` (`artifact_kind`) |
| `entries` | sorted list of `{partition, repo, freeze_commit}` |
| `count` | `len(entries)` |

### Identity helpers

| Helper | Rule |
| ------ | ---- |
| `_repo_key(row)` | first non-empty of `repo_path`/`url`/`repo`/`name`/`repo_name`; else `freeze_commit[:10]`; else `repr(sorted(row.keys()))` |
| `_freeze_commit(row)` | `row["freeze_commit"]` if a non-empty `str`, else `None` |
| `_rows_from_per_repo(x)` | `x` if list (non-dict rows skipped); non-list → `[]` (logged) |

## The invariants this pins

- **Order independence:** entries sorted by `(partition, repo, freeze_commit or "")` — same repos
  in any input order produce the same digest.
- **Kind gating:** only `multi`/`generalization` carry per-repo rows; `single`/`invalid` → empty.
- **Fail-open-empty:** a non-dict artifact / non-list `per_repo` / non-dict row never raises.

## Contract surface (functions this spec pins)

`freeze_digest`, `freeze_digest_headline`, `_collect_rows`, `_rows_from_per_repo`, `_repo_key`,
`_freeze_commit`, and the `artifact_kind` dependency (`benchmark/comparability.py`).

## Verification strategy

`tests/test_spec_024_freeze_digest.py` (this PR) exercises each artifact kind, the identity
preference order, sort determinism (shuffled input), and malformed-input degradation.

## Out of scope for this plan

Changing digest behavior, `artifact_kind`, or artifact production. Code changes follow the SDD
loop in their own specs/PRs.
