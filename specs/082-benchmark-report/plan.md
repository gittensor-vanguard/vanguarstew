# Spec 082 — Plan

## Approach

`benchmark/report.py` already ships and drives `scripts/report.py`. This spec is a
**characterization** effort requested by issue #1995: document the existing rendering contract and
pin it with tests, adding no behaviour. Every asserted value in `tests/test_spec_082_report.py`
was taken from the live module, not hand-derived. `tests/test_report.py` already exercises the
renderer in breadth; this suite pins the load-bearing invariants that form the contract.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | single-repo shape | `test_single_repo_shape_renders_the_single_repo_headline_and_scores` |
| AC-2 | multi-repo shape + tally | `test_multi_repo_shape_renders_the_multi_repo_headline_and_repo_tally` |
| AC-3 | generalization shape | `test_generalization_shape_renders_gap_and_verdict` |
| AC-4 | error shape | `test_error_shape_renders_the_error_headline` |
| AC-5 | unknown shape | `test_unknown_shape_for_empty_dict_and_non_dict` |
| AC-6 | dispatch precedence (scored wins over error) | `test_error_with_a_composite_mean_still_renders_as_a_scored_report_not_error` |
| AC-7 | verdict threshold + override | `test_gap_verdict_flips_to_inspect_above_the_threshold`, `test_gap_threshold_is_configurable` |
| AC-8 | non-finite / oversized-int → n/a (#616) | `test_non_finite_numeric_fields_render_na_not_a_crash`, `test_oversized_int_field_renders_na_not_a_crash` |
| AC-9 | unscored → n/a (#507) | `test_unscored_partition_renders_na_not_its_placeholder_zero` |
| AC-10 | malformed containers → n/a + warn (#667) | `test_non_list_per_repo_degrades_to_no_table_with_a_warning`, `test_malformed_composite_parts_renders_na_with_a_warning`, `test_missing_judge_report_renders_na_wlt` |
| AC-11 | purity | `test_render_report_does_not_mutate_its_input`, `test_render_report_always_returns_a_trailing_newline_terminated_string` |

## Issue coverage

Issue #1995 asks for the report contract to be written down. The concrete degradations it calls
out are the subjects of three existing bug reports, each pinned here so a regression re-trips a
test:

- **#616** — non-finite (`NaN`/`Infinity`) numeric field → `n/a` (AC-8).
- **#507** — unscored partition's placeholder `0.0` → `n/a` (AC-9).
- **#667** — non-list `per_repo` → empty table + warning, not a wrong template (AC-10).

## Risks

- **Shape-dispatch precedence is order-sensitive.** AC-6 pins the one non-obvious case (a scored
  artifact with a stray `error` still renders scored), so a reordering of the `render_report`
  branches trips a test rather than silently changing which report a user sees.
- **`n/a` degradations are the whole point.** Each malformed-input path (non-finite, oversized
  int, unscored, non-list `per_repo`, non-dict `composite_parts`, missing `judge_report`) has its
  own test so a partial regression is pinpointable.

## Out of scope

No changes to `report.py` or `scripts/report.py`. Documentation and tests only.
