# Plan 013 — repeatability assessment

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #762

Maps the [spec](./spec.md) onto `benchmark/repeatability.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_013_repeatability.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_artifacts_helper_accepts_only_real_lists`, `test_artifacts_helper_warns_on_non_list`, `test_round_helper_semantics` |
| Score extraction | `test_unscored_artifacts_are_skipped_not_counted`, `test_generalization_artifacts_score_from_tuned_partition` |
| Repeatability assessment | `test_result_always_includes_required_keys`, `test_insufficient_runs_reason_exact`, `test_statistics_are_rounded_to_three_decimals`, `test_stddev_is_sample_not_population`, `test_identical_runs_have_zero_cv_even_at_zero_mean`, `test_zero_mean_with_spread_yields_cv_none_reason_exact`, `test_cv_boundary_is_inclusive`, `test_cv_exceeds_reason_exact`, `test_thresholds_are_configurable` |
| Repeatability headline | `test_headline_no_scored_runs_exact`, `test_headline_inconclusive_exact`, `test_headline_stable_exact`, `test_headline_unstable_formats_cv_as_percentage`, `test_headline_renders_na_for_undefined_cv` |
| Pure evaluation | `test_assess_does_not_mutate_input` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_repeatability.py`.
