# Plan 085 — git freeze pipeline (snapshot export + knowable-at-T context)

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #2010

Maps the [spec](./spec.md) onto `benchmark/freeze.py` as-built. No product code.

## EARS → test mapping

New tests live in `tests/test_spec_085_freeze.py`; clauses whose discriminating test already
exists are mapped to `tests/test_freeze.py` (prefixed `existing::`) rather than re-asserted.

| Spec section | Discriminating test |
| ------------ | ------------------- |
| Constants | `test_constants_and_defaults` (the `CONTEXT_FILE` / `README_PROBE_NAMES` literals and the `lookback=50` / `scrub=True` defaults); the 4000-char cap, 10-char SHA, 10-tag window, modes, and `indent=1` are pinned in their behavior tests below |
| Git wrapper | `test_git_wrapper_stdout_return_and_pinned_failure_message` (success stdout, the exact `git {args} failed: {stderr}` message with the `.strip()`ped tail pinned, and `check=False` returning without raising on the same failing invocation); missing binary: `existing::test_git_translates_a_missing_binary_into_a_clean_runtimeerror` |
| Origin remote | `test_origin_url_exact_remote_and_empty_without_origin` |
| File snapshot | `test_file_at_exact_content_and_silent_empty_degradation` |
| Tree export | `test_export_tree_zero_exit_empty_archive_guard` (the defensive `empty archive` message, via a stubbed process), `test_export_tree_nonzero_exit_with_empty_stderr_omits_the_suffix` (empty stderr drops the `: {stderr}` suffix, no dangling `: `); non-zero exit with stderr present: `existing::test_export_tree_raises_runtime_error_for_bad_commit`; end-to-end policy application over a real `git archive` (exec bit honored, symlink dropped): `existing::test_export_tree_applies_uniform_policy_to_git_archive` |
| Tar member resolution | `test_safe_target_normalizes_backslashes_dots_and_absolute_names`, `test_safe_target_rejects_traversal_and_empty_resolutions` (each rejection pinned to the `unsafe path in archive` message, distinct from the residual `path escapes destination` one) |
| Extraction policy | `test_safe_extractall_normalizes_explicit_directory_modes` (dir mode `0o755` regardless of the recorded mode — the one mode rule no existing test pins), `test_safe_extractall_file_exec_bit_is_owner_execute_only` (the exec test is `mode & 0o100` — a group-execute-only file lands `0o644`, not `0o755`); file modes end-to-end: `existing::test_safe_extractall_extracts_regular_files_with_deterministic_modes`; absolute-name neutralization: `existing::test_safe_extractall_neutralizes_absolute_member_paths`; traversal rejection: `existing::test_safe_extractall_rejects_path_traversal`; link/special skips: `existing::test_safe_extractall_skips_symlinks_hardlinks_and_special_files`. The `extractfile is None` skip and the residual `path escapes destination` branch are documented as untestable |
| Context assembly — git calls | `test_build_context_exact_git_argv_sequence_and_degenerate_result` (all argv literals including `--sort=creatordate`, `-n 50`, and the five README probes; plus the `frozen_at.date is None` / empty-commits degenerate result on empty git output), `test_build_context_raises_for_unknown_commit` |
| Context assembly — record shapes | `test_context_exact_key_set_and_empty_placeholders`, `test_frozen_at_commit_is_callers_argument_truncated_not_resolved`, `test_recent_commits_shape_order_lookback_and_tab_subjects` (exact record keys, 10-char SHA, newest-first, `lookback` honored, tab-holding subject survives `split("\t", 2)`), `test_release_records_are_tag_only_without_dates` (the headline as-built: exactly one `tag` key, no `published_at`/`name`), `test_tag_line_parsing_fails_open_on_nondigit_dates_and_skips_empty_names` (parse-level fail-open on a non-digit tag date + the at-T boundary kept, via a stubbed process), `test_unparsable_frozen_ts_disables_the_filter_and_keeps_all_tags` (a non-numeric `%ct` sets `frozen_at` to None so the whole comparison is disabled and even a future-dated tag survives — fail-open, not fail-closed), `test_readme_probe_skips_empty_files_and_caps_at_4000`, `test_readme_probe_returns_the_first_non_empty_match_not_the_last` (the walk stops at the first non-empty probe); the policy-level tag filter, ordering, and windows on real repos: `existing::test_build_context_excludes_tags_created_after_freeze_time` (which also keeps a tag cut exactly at T — the `>` boundary), `existing::test_build_context_keeps_lightweight_tags_at_or_before_freeze`, `existing::test_build_context_sorts_releases_chronologically`, `existing::test_build_context_release_order_is_not_lexicographic`, `existing::test_build_context_keeps_ten_most_recent_releases` |
| Frozen write | `test_write_frozen_writes_scrubbed_context_inside_exported_tree` (tree + context file side by side, on-disk JSON equals the returned dict, scrub-default flag present, `indent=1` layout), `test_write_frozen_scrub_false_writes_raw_git_context` |

## Verification strategy

One contract-test group per EARS section, split between the two files so they stay
complementary: this file owns the new angles (exact argv and message literals, exact key sets
and record shapes, the `frozen_at.commit` pass-through and date-less-release as-built quirks,
the parse-level fail-open branches, and the `write_frozen` composition), while
`tests/test_freeze.py` already pins the policy-level tag filtering and ordering (#107/#332),
the extraction policy's modes/skips/rejections (#173), and the archive/binary error surfaces
(#355/#1188), and is referenced per clause above instead of duplicated. Expected values are
pinned as **literal** argv lists, message strings, and dicts rather than rebuilt from the
module's constants, so a silent flag, separator, or key change is caught here instead of
masked. Tests run fully offline against tiny throwaway git repos created under `tmp_path`
with explicit committer identity and pinned `GIT_COMMITTER_DATE`s (neutral `mylib`-style
fixtures, no scored-repo names); the branches real git cannot produce — a zero-exit empty
archive, malformed log/tag lines, a non-numeric `%ct` — are driven through a monkeypatched
`subprocess.run` at the module boundary. Each clause→test row above was spot-checked by
mutating `benchmark/freeze.py` (boundary flip on the tag filter, release-record key changes,
cap and prefix off-by-ones, maxsplit removal, scrub-default flip, argv flag edits,
check-semantics inversion) and confirming the named test fails.
