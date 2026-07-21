# Plan 069 — generalization gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1926

Maps the [spec](./spec.md) onto `benchmark/generalization_gate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_069_generalization_gate.py` |
| ------------ | ---------------------------------------------------- |
| Constants | `test_constants` |
| Numeric helper (`_is_number`, `_num`) | `test_is_number_rejects_bool_nonfinite_oversized`, `test_num_format`, `test_dict_helper` |
| Partition composite (`_composite`) | `test_composite_placeholder_zero`, `test_composite_single_repo_keeps_zero`, `test_composite_nan_missing_nondict` |
| Held-out repo count (`_scored_repos`) | `test_scored_repos_explicit`, `test_scored_repos_per_repo_excludes_skipped`, `test_scored_repos_nonlist_and_nondict_entry` |
| Partition error scan (`_partition_error`) | `test_partition_error_both_partitions` |
| Gate result (`check_generalization`) | `test_gate_result_shape_and_order`, `test_gate_generalizes`, `test_gate_overfit_gap`, `test_gate_negative_gap_within_tolerance`, `test_gate_non_dict_result_fails_closed`, `test_gate_echoes_caller_thresholds` |
| Checks-row sanitation | `test_check_rows_list_none_and_nonlist`, `test_check_rows_list_skips_bad_rows` |
| Failed checks and headline | `test_failed_checks`, `test_headline_no_checks`, `test_headline_generalizes_exact`, `test_headline_overfit_exact` |
| Pure evaluation | `test_does_not_mutate_input` |

## Verification strategy

One contract-test group per EARS section, mirroring the merged sibling gate specs (059
score-integrity, 060 error-repo-share, 061 objective-integrity). Expected detail and headline
strings are pinned as **literal** values built from concrete, platform-independent numeric inputs
(e.g. `0.70`, `0.65`) and the module's fixed `.3f` `_num` format, rather than rebuilt from the
module's own formatting, so a silent wording change is caught and no literal depends on the host
platform. The warning path (`_check_rows_list` non-list) is asserted via `caplog` so the
requirement is testable, not narrative. This module uses the shared `_is_number`/`_partition_error`
helpers unchanged — the standard finiteness/`OverflowError`-guarded form — so there is **no
divergence** from its siblings to document. Integration and CLI coverage stay in
`tests/test_generalization_gate.py`.
