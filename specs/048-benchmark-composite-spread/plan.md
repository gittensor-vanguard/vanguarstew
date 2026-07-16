# Plan 048 — composite spread summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1141

Maps the [spec](./spec.md) onto `benchmark/composite_spread.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_048_composite_spread.py` |
| ------------ | --------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Numeric semantics | `test_is_number_rejects_bool`, `test_round3_happy_path_and_invalid` |
| Headline partition | `test_headline_partition_single_and_generalization` |
| Composite parts | `test_headline_parts_happy_path`, `test_headline_parts_missing_or_malformed` |
| Composite spread summary | `test_summarize_happy_path`, `test_generalization_reads_tuned`, `test_missing_parts_none_spread`, `test_summary_always_includes_required_keys` |
| Composite spread headline | `test_headline_exact_format`, `test_headline_none_spread_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_composite_spread.py`.
