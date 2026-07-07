# Plan 042 — offline share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1103

Maps the [spec](./spec.md) onto `benchmark/offline_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_042_offline_share.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Slice summary | `test_slice_summary_happy_path`, `test_slice_summary_zero_total_share_none`, `test_slice_summary_malformed_stats`, `test_slice_summary_negative_counts` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions_and_overall`, `test_generalization_partial_partition_withholds_overall`, `test_generalization_malformed_partition_does_not_crash`, `test_invalid_kind_returns_none_fields`, `test_summary_always_includes_required_keys` |
| Offline share headline | `test_headline_happy_path_exact_format`, `test_headline_zero_total_unavailable`, `test_headline_none_share_shows_na`, `test_headline_nan_share_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_offline_share.py`.
