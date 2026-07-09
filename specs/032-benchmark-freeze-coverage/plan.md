# Plan 032 — freeze coverage summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #928

Maps the [spec](./spec.md) onto `benchmark/freeze_coverage.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_032_freeze_coverage.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict` |
| Freeze-commit detection | `test_has_freeze_commit_non_empty_str`, `test_empty_or_missing_freeze_not_counted` |
| Per-repo row parsing | `test_per_repo_none_yields_empty_rows`, `test_per_repo_non_list_warns_and_empty`, `test_malformed_row_skipped_with_warning` |
| Slice summary | `test_slice_summary_computes_rate`, `test_slice_summary_zero_rows_coverage_none` |
| Artifact-kind branches | `test_single_with_and_without_freeze`, `test_multi_repo_coverage`, `test_generalization_partitions_and_aggregate`, `test_invalid_kind_returns_zeros` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Freeze coverage headline | `test_headline_no_rows_when_zero_total`, `test_headline_multi_happy_path`, `test_headline_generalization_includes_partitions`, `test_headline_nan_rate_shows_na` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Headline branch coverage

| Branch | Test |
| ------ | ---- |
| `repos_total` not int or `<= 0` | `test_headline_no_rows_when_zero_total` |
| `kind == "generalization"` with usable totals | `test_headline_generalization_includes_partitions` |
| other kinds with usable totals | `test_headline_multi_happy_path` |
| non-finite / non-numeric rate in summary | `test_headline_nan_rate_shows_na` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_freeze_coverage.py`.
