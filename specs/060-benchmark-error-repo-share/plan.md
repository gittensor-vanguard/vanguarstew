# Plan 060 — error repo share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1695

Maps the [spec](./spec.md) onto `benchmark/error_repo_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_060_error_repo_share.py` |
| ------------ | ------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty`, `test_is_int_and_is_number_semantics` |
| Error detection | `test_has_error_truthy_absent_and_non_dict` |
| Per-repo flags | `test_repo_error_flags_dict_and_string_rows`, `test_repo_error_flags_skips_non_countable`, `test_per_repo_list_does_not_double_count_top_level_error`, `test_empty_per_repo_yields_empty_flags` |
| Share helper | `test_error_share_empty_and_populated` |
| Error repo share summary | `test_multi_share`, `test_generalization_partitions`, `test_invalid_and_empty_slice`, `test_summary_always_includes_required_keys` |
| Error repo share headline | `test_headline_exact_format`, `test_headline_no_repos`, `test_headline_n_a_share` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / missing-key branch called
out in the spec has an asserting test (lessons from Spec 057 / Spec 059 rejections). Integration
and CLI tests stay in `tests/test_error_repo_share.py`.
