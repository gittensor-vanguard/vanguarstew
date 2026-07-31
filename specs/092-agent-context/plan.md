# Plan 011 — agent knowable-at-T context

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #2007

Maps the [spec](./spec.md) onto `agent/context.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_011_agent_context.py` |
| ------------ | ---------------------------------------------- |
| Constants and alignment binding | `test_constants_and_probe_order`, `test_freeze_imports_probe_names`, `test_agent_issue_pr_list_alias_identity` |
| Forward-reference scrubbing | `test_scrub_non_string_and_empty`, `test_scrub_masks_deep_links_scheme_and_schemeless`, `test_scrub_preserves_bare_repo_and_lookalike_host`, `test_scrub_peels_trailing_punctuation`, `test_scrub_masks_issue_refs`, `test_scrub_sha_length_windows`, `test_scrub_preserves_numeric_tokens` |
| Repo layout | `test_layout_bad_path_silent_empty`, `test_layout_limit_coercion`, `test_layout_sorted_dirs_suffixed_and_excluded`, `test_layout_excluded_do_not_consume_cap`, `test_layout_cap_enforced`, `test_layout_unlistable_warns_and_degrades` |
| Layout attachment | `test_with_repo_layout_non_dict_identity_passthrough`, `test_with_repo_layout_new_dict_and_override` |
| Context loading | `test_load_context_valid_file_with_derived_layout`, `test_load_context_overrides_file_repo_layout`, `test_load_context_non_dict_json_passthrough`, `test_load_context_invalid_json_warns_and_rebuilds`, `test_load_context_binary_content_warns_and_rebuilds`, `test_load_context_oserror_warns_and_rebuilds`, `test_load_context_absent_file_uses_git_fallback` |
| Agent list guard | `test_list_guard_identity_none_and_warning` |
| Agent-facing view | `test_view_non_dict_context_warning_wording`, `test_view_does_not_mutate_and_preserves_unknown_keys`, `test_view_non_dict_row_passthrough_with_indexed_warning`, `test_view_labels_identity_semantics`, `test_view_labels_kept_verbatim_with_flag`, `test_view_always_emits_six_list_keys`, `test_view_truncation_flags_identity_semantics` |
| Git-only fallback | `test_fallback_empty_repo_runtime_error_literal`, `test_fallback_commit_rows_shape_and_scrub`, `test_fallback_commit_cap_50`, `test_fallback_release_rows_and_cap_10`, `test_fallback_excludes_future_dated_tags`, `test_fallback_readme_priority_and_empty_skip`, `test_fallback_readme_4000_char_cap`, `test_fallback_result_shape_and_provenance` |
| Scope of I/O | (implicit: pure helpers exercised with no filesystem; loaders exercised only against tmp_path checkouts) |

## Verification strategy

One contract-test group per EARS section, mirroring the merged agent/benchmark spec pattern
(Specs 006–010, 059–067, 073–077). Expected scrub results, warning messages, and the
empty-repo `RuntimeError` text are pinned as **literal** strings so a silent wording change is
caught; warnings are asserted via `caplog` on the `agent.context` logger. Identity semantics
(`labels_as_of_t is True`, truncation flags, the alias, list pass-through) are asserted with
`is` checks, not truthiness. Git fixtures are built inline in `tmp_path` with
`core.fsync none` (the CI-safe config), and the `OSError` load arm is driven by a selective
`builtins.open` monkeypatch that leaves the fallback's own reads untouched — deterministic and
offline throughout. Integration coverage (prompt renderers, cross-builder scrubber alignment)
stays in `tests/test_context.py` / `tests/test_scrubber_alignment.py`.
