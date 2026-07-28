# Spec 078 — Plan

## Approach

`benchmark/github_context.py` already ships and is exercised by `tests/test_github_context.py`.
Issue #1993 asks for the knowable-at-T contract to be written down; writing it out surfaced three
places where the as-built behavior was narrower or wider than the module's own docstrings already
claimed (non-GitHub remote handling, trailing-slash `.git` strip, naive-timestamp crash). Unlike a
pure characterization spec, this one fixes those three bugs in `benchmark/github_context.py`
alongside documenting the rest of the contract as-is — the fixes are real behavior changes, each
gated by a regression test; everything else in the spec is pinned, not changed.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | non-GitHub remote → `(None, None)` | `test_parse_owner_repo_rejects_non_github_remotes` |
| AC-2 | `.git` strip survives a trailing slash | `test_parse_owner_repo_strips_git_suffix_before_trailing_slash` |
| AC-3 | subpaths ignored | `test_parse_owner_repo_ignores_trailing_subpaths` |
| AC-4 | naive timestamp → `None` | `test_parse_dt_rejects_naive_timestamps`, `test_parse_dt_tolerates_unusable_timestamps` |
| AC-5 | open-at-T inclusive boundaries, naive-safe | `test_item_open_at_gates_by_created_and_closed`, `test_item_open_at_boundary_created_or_closed_exactly_at_T`, `test_item_open_at_missing_created_at_is_not_open`, `test_item_open_at_does_not_raise_on_naive_timestamps` |
| AC-6 | timeline close correction, order-independent | `test_closed_at_from_timeline_corrects_a_closed_then_reopened_item`, `test_closed_at_from_timeline_no_correction_when_reopened_before_T`, `test_closed_at_from_timeline_no_events_means_no_correction` |
| AC-7 | labels `None` vs `[]` | `test_labels_at_none_when_nothing_reconstructable`, `test_labels_at_reconstructs_membership_as_of_T` |
| AC-8 | title reconstruction / live fallback | `test_title_at_uses_live_title_when_no_renames`, `test_title_at_returns_title_before_post_T_rename`, `test_issue_record_fails_closed_on_truncated_timeline_even_with_renames` |
| AC-9 | labels+title fail closed together | `test_issue_record_fails_closed_on_truncated_timeline_even_with_renames`, `test_issue_record_fails_title_closed_when_timeline_unavailable` |
| AC-10 | unavailable timeline reports truncated | `test_issue_timeline_signals_truncation`, `test_issue_timeline_marks_truncated_on_error_after_first_page` |
| AC-11 | milestone state as-of-T, naive-safe | `test_milestone_state_is_as_of_T`, `test_milestone_boundary_closed_at_T_and_omits_due_on`, `test_milestone_at_does_not_raise_on_naive_timestamps` |
| AC-12 | release filter + name omitted | `test_releases_filtered_by_published_at_including_boundary_and_drafts`, `test_release_name_is_not_copied_live` |
| AC-13 | pagination cap discards the list | `test_truncation_flag_when_page_cap_hit`, `test_releases_fail_closed_when_list_pagination_cap_hit`, `test_milestones_fail_closed_when_list_pagination_cap_hit` |
| AC-14 | backlog gate checks `is True` | `test_open_issues_from_context_omits_truncated_backlog`, `test_open_issues_from_context_keeps_backlog_when_truncated_is_not_boolean_true` |
| AC-15 | enrichment degrades on failure | `test_enrich_context_degrades_on_failure`, `test_enrich_context_returns_non_dict_context_unchanged`, `test_enrich_context_tolerates_non_dict_frozen_at` |

## Risks

- **Naive-timestamp fix changes observable output for malformed input only.** A hand-built or
  corrupted timestamp without a UTC offset now degrades (field omitted / item excluded) instead
  of crashing the whole enrichment via `enrich_context`'s catch-all. Real GitHub API responses
  always carry an offset, so this cannot change behavior against a live repo — only against the
  synthetic/malformed inputs the new tests construct.
- **Remote-parsing fix rejects previously-"handled" non-GitHub remotes.** A non-GitHub remote used
  to produce a wrong-namespace API call that failed and degraded to git-only context anyway; it
  now short-circuits to the same git-only degradation without the wasted request. Net-visible
  behavior for a real repo is unchanged (still git-only), just reached without an extra network
  round-trip.

## Out of scope

No changes beyond the three fixes named in the spec. `audit_context`, `_get`/`_get_all` transport
behavior, and default page-cap values are untouched.
