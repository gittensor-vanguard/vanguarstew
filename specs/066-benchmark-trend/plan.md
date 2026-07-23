# Plan 066 — benchmark score trend

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1889

Maps the [spec](./spec.md) onto `benchmark/trend.py` as-built. No product code.

## EARS → test mapping

The test file is ordered load-bearing-first (the inherited `headline_score` contract and the
regression math lead), so a truncated diff view still shows the criteria that matter most.

| Spec section | Test group in `test_spec_066_trend.py` |
| ------------ | -------------------------------------- |
| Headline score extraction | `test_headline_score_non_dict_is_none`, `test_tuned_source_requires_both_partitions_to_be_dicts`, `test_zero_scored_repos_placeholder_is_unscored`, `test_bool_negative_and_string_scored_repos_keep_the_score`, `test_composite_mean_rounded_to_three_places`, `test_genuine_zero_composite_is_kept` |
| Trend summary | `test_summary_always_includes_required_keys`, `test_points_deltas_and_counts`, `test_unscored_point_bridges_the_delta`, `test_empty_series_summary_is_all_none`, `test_non_finite_subtraction_yields_none_delta_and_change`, `test_single_scored_point_change_is_zero`, `test_regressions_shape_and_drop_sign`, `test_drop_equal_to_threshold_is_not_a_regression`, `test_regression_threshold_is_echoed_and_unvalidated` |
| Series and entry sanitation | `test_non_list_series_is_empty_and_none_is_silent`, `test_entry_must_be_a_two_element_sequence`, `test_malformed_entry_does_not_abort_the_series` |
| Numeric guard | `test_is_number_rejects_bool_non_finite_and_non_numeric`, `test_is_number_returns_false_for_oversized_int` |
| Constants | `test_default_regression_threshold_value` |
| Trend headline | `test_headline_no_scored_artifacts`, `test_headline_arrow_and_change_formatting`, `test_headline_non_numeric_change_renders_n_a`, `test_headline_tolerates_non_list_regressions` |
| Pure analysis | `test_trend_does_not_mutate_or_copy_its_inputs` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / missing-key branch called
out in the spec has an asserting test (lessons from the Spec 057 / Spec 059 incompleteness
rejections), including the **emission** of each sanitizer warning and the `%r` rendering of a
skipped entry — not merely the silent-on-`None` direction. Expectations are **pinned literals**
— no test derives its expected value by calling the function under test — so a neutered
implementation cannot satisfy them.

Verified by mutation: 14 mutants of `benchmark/trend.py` (tuned-partition rule, the
`scored_repos` placeholder, threshold exclusivity, the round-before-compare, the `list` check,
`bool` rejection, entry arity, `composite_mean` rounding, the `_round` finite guard, and each
`logger.warning` call and its `%r`) are each caught by this file alone.

Integration and CLI coverage stay in `tests/test_trend.py`; this file asserts the contract the
six sibling gates (`regression`, `improvement`, `gap_outlook`, `artifact_snapshot`,
`repeatability`, `leaderboard`) inherit from `headline_score`.
