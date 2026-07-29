# Plan 068 — improvement (adoption) gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1900

Maps the [spec](./spec.md) onto `benchmark/improvement.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_068_improvement.py` |
| ------------ | -------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_dict_helper`, `test_num_formats_three_decimals_or_na` |
| Score and cleanliness sources | `test_headline_source_generalization_vs_top_level`, `test_headline_source_lone_tuned_is_top_level`, `test_scores_reject_non_finite_and_placeholder`, `test_artifact_error_scans_three_sites`, `test_artifact_error_ignores_held_out_and_falsy`, `test_artifact_error_ignores_malformed_containers` |
| Gate | `test_result_carries_all_keys`, `test_adopts_on_sufficient_gain`, `test_holds_on_insufficient_gain_keeps_detail_form`, `test_holds_on_negative_gain`, `test_both_scored_baseline_error_precedence`, `test_both_scored_reports_candidate_error`, `test_both_scored_missing_score_and_none_artifacts`, `test_min_gain_is_raw_nan_and_neg_inf_arms` |
| Check-row sanitation | `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_warns_on_non_list`, `test_check_rows_list_skips_and_warns_on_malformed_rows`, `test_check_rows_list_accepts_empty_name_here`, `test_check_rows_list_rejects_numpy_bool`, `test_check_rows_list_warns_when_no_usable_rows` |
| Failed checks and headline | `test_failed_checks_names_and_non_dict`, `test_headline_no_checks`, `test_headline_adopt_literal`, `test_headline_adopt_renders_na_triple`, `test_headline_hold_counts_sanitized_rows_only` |
| Pure evaluation | `test_check_does_not_mutate_inputs` |

## Verification strategy

One contract-test group per EARS section. This directly addresses each closure finding on the
prior Spec 068 attempt (#1901): the `_headline_source`-without-`held_out` arm is **specified and
pinned** (a lone `tuned` dict is not the headline — the top level is), `_partition_error`'s
three scan sites are specified with a test per site (partition `error`, `per_repo` dict-row
`error`, malformed string row) plus the intentionally ignored `held_out` failure, the warning
requirements are **testable** (asserted with `caplog` on the exact `benchmark.improvement`
logger, per branch), the headline format is specified completely (ADOPT literal, the
`n/a` triple for missing fields, HOLD counts over sanitized rows only, the no-checks line), and
the negative-gain and `None`-artifact cases are pinned. Every literal has a platform-stable
`repr` (three-decimal `_num` renderings, fixed `repr` strings for error values).

Beyond the finding list, the raw-`min_gain` asymmetry (`0.02` interpolates unformatted; a `NaN`
threshold fails all comparisons, `-inf` passes any) and the falsy-error skip are pinned so a
silent guard added later is caught. numpy is not a test dependency; the numpy-bool rejection
uses a type-name stand-in. Integration and CLI coverage stay in `tests/test_improvement.py`.
