# Plan 019 — cross-artifact comparability gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #819

How the [spec](./spec.md) maps onto `benchmark/comparability.py` as-built. No new product code.

## Architecture / control flow

```
artifact_kind(artifact) → single | multi | generalization | invalid

check_comparability(artifacts)
  ├─ enough_artifacts
  ├─ same_artifact_kind
  └─ same_repo_set / tuned_same_repo_set / held_out_same_repo_set

failed_checks(result) → list[str]
comparability_headline(result) → str
```

## EARS → test mapping

| Spec section | Test group in `test_spec_019_comparability.py` |
| ------------ | --------------------------------------------- |
| Artifact kind classification | `test_artifact_kind_*` |
| Repo identity extraction | `test_repo_key_*`, `test_malformed_per_repo_*` |
| Comparability checks | `test_check_comparability_*` |
| Malformed gate-result robustness | `test_failed_checks_*`, `test_check_rows_list_*` |
| Comparability headline | `test_comparability_headline_*` |
| Pure evaluation | `test_check_comparability_does_not_mutate_inputs` |

## Verification strategy

One contract-test group per EARS section; integration/CLI tests stay in `tests/test_comparability.py`.
