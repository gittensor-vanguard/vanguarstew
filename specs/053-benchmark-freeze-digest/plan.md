# Plan 053 — freeze digest summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1162

Maps the [spec](./spec.md) onto `benchmark/freeze_digest.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_053_freeze_digest.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Repo identity | `test_repo_key_prefers_name_fields`, `test_repo_key_falls_back_to_freeze_or_keys_repr` |
| Freeze commit | `test_freeze_commit_string_or_none` |
| Per-repo row parsing | `test_rows_from_per_repo_none_and_non_list`, `test_rows_from_per_repo_skips_non_dict_entries` |
| Row collection | `test_collect_rows_multi_and_generalization`, `test_collect_rows_single_empty` |
| Freeze digest | `test_digest_sorted_entries`, `test_single_kind_empty_entries`, `test_summary_always_includes_required_keys` |
| Freeze digest headline | `test_headline_singular_and_plural`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_freeze_digest_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_freeze_digest.py`.
