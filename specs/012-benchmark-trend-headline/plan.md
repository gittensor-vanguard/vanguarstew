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
| Headline score — **rounding mode** (banker's, ties, negative tie) | `test_rounding_mode_is_round_half_to_even`, `test_headline_score_rounding_ties_pinned`, `test_round_helper_ties_pinned` |
| Series coercion (`_trend_series`, `_trend_point`) | `test_trend_series_accepts_only_lists`, `test_trend_point_accepts_only_two_element_pairs`, `test_non_list_series_yields_empty_summary`, `test_malformed_entries_are_skipped_not_unpacked` |
| Trend summary — points/deltas/first-last | `test_points_deltas_and_overall_change`, `test_delta_bridges_across_unscored_points`, `test_first_last_use_scored_values_only`, `test_min_max_range_independent_of_endpoints`, `test_result_always_includes_required_keys`, `test_empty_series_summary`, `test_single_scored_point_has_no_delta` |
| Trend summary — regressions | `test_regression_only_beyond_threshold`, `test_regression_drop_exactly_at_threshold_is_not_flagged`, `test_regression_threshold_is_configurable_and_echoed`, `test_round_helper` |
| Trend summary — **endpoint-only-scored** (bridging) | `test_regression_detected_across_endpoint_only_scored_series`, `test_endpoint_only_scored_rise_has_no_regression`, `test_two_scored_endpoints_minimal`, `test_scored_then_unscored_endpoint`, `test_unscored_then_scored_endpoint` |
| Trend headline (`trend_headline`) | `test_headline_line_up_down_flat`, `test_headline_line_no_scored_artifacts`, `test_headline_line_non_dict_summary`, `test_headline_line_non_numeric_change_is_na`, `test_headline_line_non_list_regressions_counts_zero` |
| Pure evaluation | `test_trend_does_not_mutate_input_for_every_shape`, `test_trend_performs_no_io` |

## Result-field semantics pinned (avoid ambiguity)

| Field / behavior | Rule | Test |
| ---------------- | ---- | ---- |
| **rounding mode** | every score/delta/change/drop is `round(float(x), 3)` using Python's built-in `round` = **round-half-to-even (banker's rounding)**, per Python built-in `round`. On an exact binary tie it picks the even digit (`round(2.5, 0) == 2.0`); a 3-decimal `…5` literal is not an exact tie, so it follows the float's nearer neighbour (`0.0005 → 0.001`, `0.1235 → 0.123`, `-0.0005 → -0.001`) — fully pinned, no ambiguity | `test_rounding_mode_is_round_half_to_even`, `test_headline_score_rounding_ties_pinned`, `test_round_helper_ties_pinned` |
| `delta` | change from the previous **scored** point (not the previous point); `None` for the first scored point and any unscored point | `test_delta_bridges_across_unscored_points` |
| `first` / `last` | the first / last **scored** values, skipping leading/trailing unscored points | `test_first_last_use_scored_values_only` |
| `change` vs `min`/`max` | `change = round(last − first, 3)` (signed) is independent of the `min`/`max` range, which spans all scored points (mid-series spike/dip included) | `test_points_deltas_and_overall_change`, `test_min_max_range_independent_of_endpoints` |
| `regression.drop` | positive magnitude, only for a drop **strictly** `> threshold` (`round(from − to, 3)`) | `test_regression_only_beyond_threshold`, `test_regression_drop_exactly_at_threshold_is_not_flagged` |
| **endpoint-only-scored** | `[scored, unscored, …, unscored, scored]`: the middle is bridged as one step; the trailing delta is `last − first`; a beyond-threshold drop is reported **once** naming the two scored **endpoints** as `from_label`/`to_label`; `scored == 2`, `total` counts all surviving points; a rising pair flags no regression. 2-point degenerate shapes follow the same rules | `test_regression_detected_across_endpoint_only_scored_series`, `test_endpoint_only_scored_rise_has_no_regression`, `test_two_scored_endpoints_minimal`, `test_scored_then_unscored_endpoint`, `test_unscored_then_scored_endpoint` |
| `scored_repos: 0` `0.0` | placeholder for an unscored aggregate → `None`, distinct from a genuine `0.0` | `test_headline_scored_repos_zero_placeholder_is_unscored`, `test_headline_genuine_zero_is_preserved` |

## Verification strategy

One contract-test group per EARS section; every assertion is pinned against the live output of the
as-built module (the rounding-tie and endpoint-only-scored outputs were captured by running the
real functions on the target before pinning). Integration and CLI tests stay in `tests/test_trend.py`.
