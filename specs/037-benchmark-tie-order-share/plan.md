# Plan 037 — tie order share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #987

Maps the [spec](./spec.md) onto `benchmark/tie_order_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_037_tie_order_share.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Slice summary | `test_slice_summary_happy_path`, `test_slice_summary_zero_total_share_none`, `test_slice_summary_malformed_stats`, `test_slice_summary_negative_counts` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions_and_overall`, `test_generalization_partial_partition_withholds_overall`, `test_generalization_malformed_partition_does_not_crash`, `test_invalid_kind_returns_none_fields`, `test_summary_always_includes_required_keys` |
| Tie order share headline | `test_headline_happy_path_exact_format`, `test_headline_zero_total_unavailable`, `test_headline_none_share_shows_na`, `test_headline_nan_share_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Headline branch coverage

| Branch | Test |
| ------ | ---- |
| `total` not int or `<= 0` | `test_headline_zero_total_unavailable` |
| `total > 0` with valid share | `test_headline_happy_path_exact_format` |
| `tie_order_share` is `None` | `test_headline_none_share_shows_na` |
| non-finite share | `test_headline_nan_share_shows_na` |
| non-dict summary | `test_headline_non_dict_summary_coerced` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_tie_order_share.py`.
