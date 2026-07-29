# Spec 082 — Plan

## Approach

`benchmark/report.py` already ships and is exercised in breadth by `tests/test_report.py`. This
spec is a **characterization** effort, same as Spec 076 for the leaderboard: document the existing
contract and pin it with a dedicated test file, adding no behaviour. Every asserted value in
`tests/test_spec_082_report.py` was read off the live module, not hand-derived.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | shape dispatch precedence, no raise on any shape | `test_dispatch_prefers_generalization_over_error_and_multi_repo`, `test_dispatch_prefers_multi_repo_over_single_repo`, `test_unknown_shape_for_non_dict_input`, `test_unknown_shape_for_dict_matching_nothing` |
| AC-2 | scored artifact with stray error still renders scored | `test_single_repo_with_stray_error_still_renders_single_repo`, `test_multi_repo_with_stray_error_still_renders_multi_repo` |
| AC-3 | generalization gap verdict + configurable threshold + n/a gap | `test_generalization_verdict_pass_and_inspect`, `test_generalization_verdict_respects_custom_threshold`, `test_generalization_verdict_is_na_for_missing_or_non_finite_gap` |
| AC-4 | non-finite / oversized numeric fields render n/a | `test_non_finite_composite_and_judge_fields_render_na`, `test_oversized_int_field_renders_na` |
| AC-5 | scored_repos: 0 renders n/a not placeholder 0.0 | `test_unscored_partition_renders_na_not_placeholder_zero` |
| AC-6 | malformed per_repo -> no table + warning; absent/empty -> silent | `test_non_list_per_repo_omits_table_with_warning`, `test_all_junk_per_repo_omits_table_with_warning`, `test_absent_or_empty_per_repo_omits_table_silently` |
| AC-7 | malformed composite_parts/foresight warn; missing/malformed judge_report is silent n/a | `test_malformed_composite_parts_warns_and_degrades`, `test_malformed_foresight_warns_and_degrades`, `test_missing_or_malformed_judge_report_is_silent_na` |
| AC-8 | purity: no mutation, no I/O surface | `test_render_report_does_not_mutate_any_shape` |

## Dependency note

The renderer trusts the shapes produced by `run_eval`/`run_multi_replay`/the generalization
runner; it does not itself validate that a `composite_mean` is a plausible score, only that it is
numeric. `benchmark/report.py`'s own module docstring already states the purity/degradation intent
this spec formalizes.

## Risks

- **Shape-detection overlap.** `_is_multi_repo` and `_is_generalization` both inspect fields that
  could in principle coexist on a hand-edited artifact; the dispatch order in `render_report` is
  the actual contract, so AC-1's tests assert on that order directly rather than re-deriving it.
- **Oversized-int portability.** As in Spec 076, the `10**400`-style case relies on `float()`
  raising `OverflowError`, stable across supported CPython versions; the test asserts the `n/a`
  degradation, not the exception itself.

## Out of scope

No changes to `report.py` or `scripts/report.py`. Documentation and tests only.
