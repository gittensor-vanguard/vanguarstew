# Plan 034 — scored fraction summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #960

Maps the [spec](./spec.md) onto `benchmark/scored_fraction.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_034_scored_fraction.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Scored fraction | `test_scored_fraction_valid_rates`, `test_scored_fraction_zero_scored_is_zero_point_zero`, `test_scored_fraction_negative_repos`, `test_scored_fraction_negative_scored`, `test_scored_fraction_scored_exceeds_repos`, `test_scored_fraction_zero_repos`, `test_scored_fraction_non_integer_counts` |
| Slice fraction | `test_slice_fraction_happy_path`, `test_slice_fraction_incoherent_echoes_raw_ints`, `test_slice_fraction_non_int_counts_become_none`, `test_slice_fraction_ignores_skipped_field` |
| Combined fraction | `test_combined_sums_coherent_slices`, `test_combined_withholds_when_any_slice_incoherent` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions_and_overall`, `test_generalization_partial_partition_withholds_overall`, `test_invalid_kind_returns_none_fields`, `test_summary_always_includes_required_keys` |
| Scored fraction headline | `test_headline_with_counts_exact_format`, `test_headline_zero_fraction_exact_format`, `test_headline_perfect_coverage_exact_format`, `test_headline_no_counts_clause`, `test_headline_none_fraction_shows_na`, `test_headline_nan_fraction_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_scored_fraction.py`.
