# Spec 076 — Plan

## Approach

`benchmark/leaderboard.py` already ships and is exercised indirectly. This spec is a
**characterization** effort: document the existing contract and pin it with tests, adding no
behaviour. Issue #1941 asks for the leaderboard ranking contract to be written down; the code is
the source of truth and every asserted value in `tests/test_spec_076_leaderboard.py` was taken
from the live module, not hand-derived.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | rank best-first, delta_from_best | `test_ranks_best_first_with_delta_from_best` |
| AC-2 | competition ties (1,2,2,4), input order | `test_competition_ranking_ties_share_a_rank_and_the_next_rank_skips`, `test_ties_keep_input_order` |
| AC-3 | best summary / None | `test_ranks_best_first_with_delta_from_best`, `test_all_unscored_yields_no_best_and_empty_ranking` |
| AC-4 | unscored partition | `test_entries_with_no_usable_score_are_reported_unscored_never_ranked`, `test_all_unscored_yields_no_best_and_empty_ranking` |
| AC-5 | generalization tuned headline | `test_headline_score_uses_the_tuned_partition_for_a_generalization_artifact`, `test_generalization_artifact_ranks_on_its_tuned_components` |
| AC-6 | scored_repos:0 unscored | `test_headline_score_treats_a_zero_scored_repos_aggregate_as_unscored` |
| AC-7 | component + foresight breakdown, None degrade | `test_components_expose_the_m7_foresight_axes_rounded_to_three_places`, `test_components_default_every_axis_to_none_when_absent`, `test_components_on_a_non_dict_artifact_return_all_none`, `test_a_non_finite_component_degrades_to_none_not_inf_or_nan` |
| AC-7 (numeric guard) | `_is_number` edges | `test_is_number_rejects_nan`, `test_is_number_rejects_infinity`, `test_is_number_rejects_bool`, `test_is_number_rejects_oversized_int_that_cannot_convert_to_float`, `test_is_number_accepts_a_plain_finite_number` |
| AC-8 | non-list entries warn + empty | `test_a_non_list_entries_is_treated_as_no_candidates_with_a_warning` |
| AC-9 | malformed entry skip + warn | `test_a_malformed_entry_is_skipped_not_crashed`, `test_leaderboard_point_names_the_offending_index` |
| AC-10 | headline string | `test_headline_names_the_leader_and_counts_the_field`, `test_headline_reports_unscored_tail`, `test_headline_on_an_empty_or_all_unscored_board` |

## Dependency note

`rank` extracts scores via `benchmark.trend.headline_score`; the leaderboard's behaviour is only
defined relative to that helper's contract, which is therefore stated in the spec and pinned by
dedicated tests (the generalization-partition and `scored_repos: 0` cases) rather than left
implicit. `headline_score` itself is owned by `benchmark/trend.py` and is out of scope for change
here.

## Risks

- **Portability of the oversized-int case.** `_is_number(10**400)` relies on `float()` raising
  `OverflowError`, which is stable across CPython versions; the test asserts the degradation
  (`False`), not the exception, so it stays robust.
- **Foresight axes on legacy artifacts.** Artifacts saved before the M7 foresight breakdown lack
  those keys; the spec and tests fix that they render `None`, not a fabricated `0.0`.

## Out of scope

No changes to `leaderboard.py`, `trend.py`, or the scoring modules. Documentation and tests only.
