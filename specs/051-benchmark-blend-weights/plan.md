# Plan 051 — blend weights summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1156

Maps the [spec](./spec.md) onto `benchmark/blend_weights.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_051_blend_weights.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Numeric semantics | `test_is_number_rejects_bool`, `test_is_number_accepts_numeric` |
| Headline partition | `test_headline_partition_single_and_generalization` |
| Blend weights summary | `test_summarize_happy_path`, `test_generalization_reads_tuned`, `test_missing_or_malformed_weights`, `test_summary_always_includes_required_keys` |
| Blend weights headline | `test_headline_exact_format`, `test_headline_unavailable_exact`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_blend_weights.py`.
