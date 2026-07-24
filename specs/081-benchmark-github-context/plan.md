# Plan 081 — knowable-at-T GitHub context

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1993

Maps the [spec](./spec.md) onto `benchmark/github_context.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_081_github_context.py` |
| ------------ | ------------------------------------------------ |
| Constants | `test_constants_are_pinned` |
| Remote parsing | `test_parse_owner_repo_handles_the_documented_remote_forms`, `test_parse_owner_repo_needs_two_segments`, `test_parse_owner_repo_is_not_github_specific`, `test_parse_owner_repo_git_strip_is_end_anchored` |
| Timestamp parsing | `test_parse_dt_rejects_unusable_values`, `test_parse_dt_normalizes_a_trailing_z`, `test_parse_dt_returns_a_naive_datetime_for_an_offsetless_string`, `test_naive_timestamp_propagates_a_type_error` |
| At-T membership | `test_item_open_at_requires_a_datable_creation`, `test_item_open_at_bounds_are_inclusive_at_t`, `test_item_open_at_treats_an_unusable_closed_at_as_open` |
| Timeline close correction | `test_closed_at_from_timeline_corrects_a_live_snapshot_false_positive`, `test_closed_at_from_timeline_no_toggles_means_no_correction`, `test_closed_at_from_timeline_ignores_post_t_toggles`, `test_closed_at_from_timeline_is_order_independent` |
| Issue/PR record | `test_issue_record_drops_an_item_closed_at_t`, `test_issue_record_fails_closed_on_a_truncated_timeline`, `test_issue_record_shape_and_reconstructed_fields` |
| Label reconstruction | `test_labels_at_replays_events_up_to_t_sorted`, `test_labels_at_boundary_event_is_applied`, `test_labels_at_returns_none_when_nothing_is_reconstructable`, `test_labels_at_empty_list_means_reconstructed_and_unlabeled`, `test_labels_at_warns_on_a_non_dict_event`, `test_labels_at_skips_malformed_label_payloads_silently` |
| Title reconstruction | `test_title_at_uses_the_live_title_without_renames`, `test_title_at_returns_the_from_of_the_first_post_t_rename`, `test_title_at_replays_a_pre_t_chain`, `test_title_at_boundary_rename_is_applied`, `test_title_at_warns_on_a_non_dict_rename_payload` |
| Milestones | `test_milestone_at_drops_an_undatable_or_future_milestone`, `test_milestone_state_is_derived_as_of_t`, `test_milestone_never_carries_title_or_due_on` |
| Pagination | `test_get_all_stops_on_a_short_page`, `test_get_all_flags_truncation_only_at_the_cap_with_a_full_page`, `test_get_all_appends_page_to_an_existing_query_string`, `test_get_all_propagates_a_request_error`, `test_issue_timeline_reports_an_unavailable_timeline_as_truncated`, `test_issue_timeline_event_less_fetch_is_complete`, `test_collect_open_at_routes_prs_and_flags_the_cap` |
| Fetch | `test_fetch_defaults_the_token_from_the_environment`, `test_fetch_discards_a_truncated_issue_backlog`, `test_fetch_discards_truncated_milestone_and_release_lists`, `test_fetch_keeps_only_published_releases_without_a_name`, `test_fetch_result_shape_and_no_label_catalog` |
| Enrichment | `test_enrich_returns_a_non_dict_context_unchanged_with_a_warning`, `test_enrich_without_a_resolvable_remote_or_freeze_date_is_a_no_op`, `test_enrich_merges_only_the_documented_keys`, `test_enrich_degrades_with_a_truncated_error_annotation`, `test_frozen_at_date_tolerates_unusable_shapes` |
| Backlog gate | `test_open_issues_from_context_rejects_a_truncated_backlog`, `test_open_issues_from_context_checks_identity_not_truthiness`, `test_open_issues_from_context_passes_the_value_through` |

## Verification strategy

One contract-test group per EARS section; every fail-closed / truncated / malformed / boundary
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections and
the finding lists on the closed Spec 068 / 069 PRs). **No test performs network I/O**: `_get` is
monkeypatched with an in-memory router, matching `tests/test_github_context.py`'s existing posture,
so the page-walk and truncation rules are exercised on the real code path rather than mocked away.

Expectations are **literal** — exact record dicts, exact sorted label lists, exact `(items,
truncated)` tuples — rather than re-derived from the module. The at-T boundary is asserted at the
*exact* instant on every gate that has one (`_item_open_at` on both `created_at` and `closed_at`,
`_labels_at`, `_title_at`, `_milestone_at`), because "inclusive at T" is precisely the kind of
detail a refactor flips without any test noticing.

Three pairs that mean opposite things get dedicated tests, since collapsing either pair is the
realistic regression: `_labels_at` returning `None` (not reconstructable → the caller omits and
reports `labels_as_of_t=False`) versus `[]` (reconstructed, genuinely unlabelled at T);
`_issue_timeline` returning `([], True)` for an *unavailable* timeline versus `([], False)` for a
fetched, event-less one — the difference between omitting a title and leaking a post-T rename; and
`open_issues_from_context`'s `is True` identity check versus truthiness. The two logging branches
(`_labels_at` on a non-dict event, `_title_at` on a non-dict rename payload) are asserted via
`caplog` on the `benchmark.github_context` logger, and the silently-skipped malformed payloads
assert the *absence* of a warning so the distinction is not left untested.

The naive-timestamp path is verified positively rather than assumed: one test pins that
`_parse_dt` returns a naive `datetime` for an offset-less string, and one pins that the resulting
`TypeError` reaches the caller — with `enrich_context` shown degrading to a `_github_error`
annotation, which is what actually happens in a run. Integration coverage stays in
`tests/test_github_context.py`.
