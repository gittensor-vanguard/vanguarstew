# Plan 052 — gap outlook summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1160

Maps the [spec](./spec.md) onto `benchmark/gap_outlook.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_052_gap_outlook.py` |
| ------------ | -------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Numeric semantics | `test_is_number_rejects_bool`, `test_is_number_accepts_numeric` |
| Partition score | `test_partition_score_happy_path`, `test_partition_score_zero_scored_repos` |
| Gap outlook summary | `test_generalization_favorable_and_unfavorable`, `test_non_generalization_none_fields`, `test_summary_always_includes_required_keys` |
| Gap outlook headline | `test_headline_generalization_exact_format`, `test_headline_non_generalization_exact`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_gap_outlook.py`.
