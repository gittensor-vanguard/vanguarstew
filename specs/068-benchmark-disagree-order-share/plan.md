# Plan 068 — disagree order share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1919

Maps the [spec](./spec.md) onto `benchmark/disagree_order_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_068_disagree_order_share.py` |
| ------------ | ----------------------------------------------------- |
| Binding | `test_binding_exports_and_stat_keys` |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty`, `test_order_stats_requires_dict` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Slice summary | `test_slice_summary_happy_path`, `test_slice_summary_zero_total_share_none`, `test_slice_summary_malformed_stats`, `test_slice_summary_negative_counts` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions_and_overall`, `test_generalization_partial_partition_withholds_overall`, `test_generalization_malformed_partition_does_not_crash`, `test_invalid_kind_returns_none_fields`, `test_summary_always_includes_required_keys` |
| Disagree order share headline | `test_headline_happy_path_exact_format`, `test_headline_zero_total_unavailable`, `test_headline_none_share_shows_na`, `test_headline_nan_share_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section, mirroring the merged sibling specs (038 agree-order-share
… 043 skip-share). Expected details and headline strings are pinned as **literal** values rather
than rebuilt from the module's own formatting, so a silent wording change is caught. This binding
uses the shared `order_share` helpers unchanged — the standard finiteness/`OverflowError`-guarded
`_is_number` — so there is **no divergence** from its siblings to document. Integration and CLI
coverage stay in `tests/test_disagree_order_share.py`.
