# Plan 078 — reference baseline maintainers

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1971

Maps the [spec](./spec.md) onto `benchmark/baselines.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_078_baselines.py` |
| ------------ | ------------------------------------------ |
| Registry | `test_registry_names_and_default`, `test_unknown_name_raises_value_error`, `test_unhashable_name_propagates_type_error` |
| Solve-call shape | `test_all_four_solves_accept_runner_call_shape_and_extra_kwargs`, `test_solve_output_has_exactly_the_judged_keys`, `test_context_as_is_including_falsy_dict`, `test_none_context_consults_load_context`, `test_empty_solve_never_touches_context_or_load_context` |
| The `empty` floor | `test_empty_solve_is_the_exact_literal_and_argument_invariant` |
| Kind inference | `test_infer_kind_precedence_release_then_conventional_commit`, `test_commit_kind_mapping_table_is_exact`, `test_keyword_bucket_order_and_substring_semantics`, `test_test_bucket_resolves_to_refactor`, `test_no_match_is_triage` |
| Context coercion | `test_issue_and_pr_title_coercion`, `test_commit_subject_non_dict_is_logged_and_becomes_placeholder`, `test_baseline_list_identity_none_and_other_types`, `test_safe_backlog_truncation_gate_is_identity_check`, `test_recent_commits_is_not_read_through_the_truncation_gate` |
| Heuristic philosophy | `test_philosophy_exact_dict_for_synthetic_context`, `test_philosophy_dominant_tie_breaks_first_seen`, `test_philosophy_empty_history_defaults_to_triage`, `test_philosophy_issue_count_includes_untitled_entries`, `test_philosophy_malformed_commit_counts_as_triage_vote_and_placeholder`, `test_philosophy_non_dict_context_matches_empty_context` |
| Heuristic plan | `test_heuristic_plan_full_section_order_as_literal`, `test_heuristic_plan_cap_is_a_plain_slice_dropping_later_sections`, `test_heuristic_plan_release_item_is_additional_to_momentum_item` |
| Queue-first | `test_review_queue_item_shape_and_number_suffix_rules`, `test_review_queue_limit_none_is_uncapped`, `test_review_queue_limit_zero_post_append_quirk`, `test_queue_first_plan_fills_from_heuristic_when_queue_short`, `test_queue_first_plan_equals_heuristic_when_queue_empty`, `test_queue_first_rationale_counts_full_queue_not_capped_items` |
| Stability-first | `test_stability_rank_table_and_unknown_kind_default`, `test_stability_first_is_a_stable_sort_of_heuristic_plan`, `test_stability_cap_applies_before_reorder` |
| Solve wrappers | `test_all_three_solves_share_heuristic_philosophy`, `test_solve_rationale_templates_are_exact` |

## Verification strategy

One contract-test group per EARS section, over small synthetic contexts built from neutral
widget/cache/parser vocabulary (never real repo names), with every expectation pinned as a
literal dict, list, or string rather than re-derived by calling the module a second time. The
two as-built quirks the spec calls out by name — the post-append `_review_queue_items` cap and
`stability_first_plan`'s cap-before-reorder — each get a dedicated test, so "fixing" either
becomes a spec-visible, deliberate change instead of a silent one. `tests/test_baselines.py`
already owns registry identity, the truncation fail-closed matrix, release-detection parity
with `benchmark/score.py`, malformed-container tolerance, and `run_replay` baseline selection;
this file does not repeat those assertions, only the exact-literal and ordering pins the spec
adds on top.
