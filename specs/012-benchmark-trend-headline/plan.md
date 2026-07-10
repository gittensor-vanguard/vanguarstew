# Plan 012 — benchmark score trend & regression gating

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #761

Maps the [spec](./spec.md) onto `benchmark/trend.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_012_trend_headline.py` |
| ------------ | ----------------------------------------------- |
| Number validity (`_is_number`) | `test_is_number_accepts_only_finite_non_bool_numbers`, `test_is_number_rejects_oversized_int_without_raising` |
| Headline score — single/multi/generalization | `test_headline_single_and_multi_read_top_level`, `test_headline_generalization_uses_tuned`, `test_headline_non_dict_is_none`, `test_headline_missing_or_non_numeric_is_none`, `test_headline_rounds_to_three_decimals` |
| Headline score — `scored_repos: 0` vs genuine `0.0` | `test_headline_scored_repos_zero_placeholder_is_unscored`, `test_headline_genuine_zero_is_preserved`, `test_headline_non_finite_composite_is_unscored` |
| Series coercion (`_trend_series`, `_trend_point`) | `test_trend_series_accepts_only_lists`, `test_trend_point_accepts_only_two_element_pairs`, `test_non_list_series_yields_empty_summary`, `test_malformed_entries_are_skipped_not_unpacked` |
| Trend summary — points/deltas/first-last | `test_points_deltas_and_overall_change`, `test_delta_bridges_across_unscored_points`, `test_first_last_use_scored_values_only`, `test_result_always_includes_required_keys`, `test_empty_series_summary`, `test_single_scored_point_has_no_delta` |
| Trend summary — regressions | `test_regression_only_beyond_threshold`, `test_regression_drop_exactly_at_threshold_is_not_flagged`, `test_regression_threshold_is_configurable_and_echoed`, `test_round_helper` |
| Trend headline (`trend_headline`) | `test_headline_line_up_down_flat`, `test_headline_line_no_scored_artifacts`, `test_headline_line_non_dict_summary`, `test_headline_line_non_numeric_change_is_na`, `test_headline_line_non_list_regressions_counts_zero` |
| Pure evaluation | `test_trend_does_not_mutate_input_for_every_shape`, `test_trend_performs_no_io` |

## Result-field semantics pinned (avoid ambiguity)

| Field / behavior | Rule | Test |
| ---------------- | ---- | ---- |
| `delta` | change from the previous **scored** point (not the previous point); `None` for the first scored point and any unscored point | `test_delta_bridges_across_unscored_points` |
| `first` / `last` | the first / last **scored** values, skipping leading/trailing unscored points | `test_first_last_use_scored_values_only` |
| `change` vs `min`/`max` | `change = last − first` (signed) is independent of the `min`/`max` range | `test_points_deltas_and_overall_change` |
| `regression.drop` | positive magnitude, only for a drop **strictly** `> threshold` (`round(from−to,3)`) | `test_regression_only_beyond_threshold`, `test_regression_drop_exactly_at_threshold_is_not_flagged` |
| `scored_repos: 0` `0.0` | placeholder for an unscored aggregate → `None`, distinct from a genuine `0.0` | `test_headline_scored_repos_zero_placeholder_is_unscored`, `test_headline_genuine_zero_is_preserved` |

## Verification strategy

One contract-test group per EARS section; every assertion is pinned against the live output of the
as-built module. Integration and CLI tests stay in `tests/test_trend.py`.
