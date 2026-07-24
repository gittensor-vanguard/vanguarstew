# Plan 078 — reference baseline maintainers

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1971

Maps the [spec](./spec.md) onto `benchmark/baselines.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_078_baselines.py` |
| ------------ | ------------------------------------------ |
| Registry | `test_registry_is_exactly_four_names_with_empty_default`, `test_unknown_name_error_message_and_unhashable_passthrough` |
| Constants | `test_philosophy_values_cap_at_the_top_three_kinds`, `test_allowed_vocabulary_is_exactly_the_seven_keyword_kinds`, `test_philosophy_evidence_caps_at_first_five_subjects` |
| Solve-call shape | `test_every_baseline_accepts_the_runner_call_shape`, `test_falsy_context_is_used_as_is_never_load_context`, `test_none_context_consults_load_context`, `test_all_four_solves_share_the_documented_signature` |
| The `empty` floor | `test_empty_solve_exact_literal_and_input_invariance` |
| Kind inference | `test_infer_kind_maps_every_conventional_commit_kind`, `test_keyword_buckets_first_match_wins_substring_semantics`, `test_keyword_bucket_order_pins_the_remaining_adjacencies` |
| Context coercion | `test_baseline_list_returns_same_object_and_rejects_tuple`, `test_truncated_context_keeps_commit_evidence_and_momentum` |
| Heuristic philosophy | `test_philosophy_exact_literal_dict`, `test_philosophy_dominant_tie_breaks_to_first_seen_kind`, `test_philosophy_counts_malformed_commits_as_triage_votes`, `test_philosophy_evidence_caps_at_first_five_subjects` |
| Heuristic plan | `test_heuristic_plan_full_section_order_as_literal_items`, `test_heuristic_plan_cap_is_a_plain_slice` |
| Queue-first | `test_review_item_shape_and_number_ref_rules`, `test_review_queue_limit_none_and_post_append_zero_quirk`, `test_queue_first_composition_queue_then_heuristic_fill`, `test_queue_first_rationale_counts_full_queue_not_capped_items` |
| Stability-first | `test_stability_rank_table_and_unknown_kind_literal`, `test_stability_first_reorders_capped_plan_as_literal`, `test_stability_cap_applies_before_reorder` |
| Solve wrappers | `test_solve_rationale_literals_and_shared_philosophy` |

## Verification strategy

One contract-test group per EARS section, over small synthetic contexts (generic widget /
cache / parser vocabulary — no real repo names), with every expectation pinned as a
**literal** dict, list, or string rather than re-derived from the module: the full six-item
heuristic plan for a four-commit/four-issue context, the exact philosophy dict including the
`""` evidence placeholder a malformed entry leaves, the exact `ValueError` message, and the
exact rationale templates with their uncapped counts. The two as-built quirks the spec calls
out — the post-append `limit<=0` review-queue item and the cap-before-reorder truncation —
each get a dedicated pin, so "fixing" either silently becomes a spec-visible change.
Registry identity, the truncation fail-closed matrix (#722/#957), release-detection parity
(#129), the ci/test bucket (#270), malformed containers (#515), and end-to-end `run_replay`
selection stay in `tests/test_baselines.py`; this file adds exact-literal and ordering pins
without repeating those assertions.
