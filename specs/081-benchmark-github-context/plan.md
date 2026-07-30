# Plan 081 — knowable-at-T GitHub context producer

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1993

Maps the [spec](./spec.md) onto `benchmark/github_context.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_081_github_context.py` |
| ------------ | ----------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Remote parsing | `test_parse_owner_repo_github_urls`, `test_parse_owner_repo_non_string`, `test_parse_owner_repo_non_github_remote`, `test_parse_owner_repo_trailing_git_slash`, `test_parse_owner_repo_too_few_segments` |
| Timestamp parsing | `test_parse_dt_usable_and_unusable`, `test_frozen_at_date_paths`, `test_naive_timestamp_raises_in_item_open_at`, `test_enrich_context_degrades_on_naive_frozen_at` |
| Open-at-T membership | `test_item_open_at_inclusive_boundaries`, `test_item_open_at_missing_created_at` |
| Timeline close correction | `test_closed_at_from_timeline_no_events`, `test_closed_at_from_timeline_corrects_reopen_after_T`, `test_closed_at_from_timeline_order_independent` |
| Timeline container | `test_timeline_events_list_and_non_list` |
| Label reconstruction | `test_labels_at_none_vs_empty_list`, `test_labels_at_chronological_replay`, `test_labels_at_skips_malformed_events` |
| Title reconstruction | `test_title_at_no_renames_uses_live`, `test_title_at_post_T_rename`, `test_title_at_rename_chain` |
| Issue timeline fetch | `test_issue_timeline_complete_empty`, `test_issue_timeline_unavailable_is_truncated`, `test_issue_timeline_page_cap_truncated` |
| Issue record assembly | `test_issue_record_truncated_fails_closed_both_fields`, `test_issue_record_labels_none_vs_empty_semantics` |
| Milestone derivation | `test_milestone_at_state_and_omissions`, `test_milestone_boundary_closed_at_T` |
| List pagination | `test_get_all_truncation_on_full_final_page`, `test_get_all_stops_on_short_page` |
| Context fetch | `test_fetch_context_at_open_at_T_filter`, `test_fetch_context_discards_partial_issues`, `test_fetch_context_releases_filtered`, `test_fetch_context_fail_closed_on_list_truncation`, `test_fetch_context_omits_labels_catalog` |
| Enrichment merge | `test_enrich_context_merges_and_sets_flag`, `test_enrich_context_non_dict_unchanged`, `test_enrich_context_degrades_on_exception`, `test_enrich_context_absent_key_preserves_base` |
| Backlog gate | `test_open_issues_from_context_truncated_is_true_only`, `test_open_issues_from_context_non_dict` |

## Verification strategy

One contract-test group per EARS section; every truncation, fail-closed, degradation, and
edge-case branch called out in the spec has an asserting test. Remote-parse quirks
(non-GitHub host, `.git/` trailing slash), naive-vs-aware `TypeError`, `_labels_at`'s `None` vs `[]`
distinction, `_closed_at_from_timeline`'s sort-before-read guarantee, unavailable-timeline
`([], True)` vs complete-empty `([], False)`, pagination cap discard rules, and the `is True`
backlog gate are each pinned with **literal** in-memory fixtures — no network. Expectations use
`repr` stable across platforms. Integration and broader regression coverage stay in
`tests/test_github_context.py`.
