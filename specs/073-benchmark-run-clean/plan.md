# Plan 073 — run-clean gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1918

Maps the [spec](./spec.md) onto `benchmark/run_clean.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_073_run_clean.py` |
| ------------ | ------------------------------------------ |
| Constants | `test_check_row_keys_pinned` |
| Helpers | `test_dict_helper`, `test_is_passed_accepts_bool_rejects_int`, `test_check_row_field` |
| Error scan | `test_top_level_error_finding`, `test_multi_per_repo_dict_error`, `test_multi_per_repo_corrupt_string`, `test_generalization_partition_and_per_repo_errors`, `test_single_artifact_scans_no_per_repo`, `test_scan_ignores_non_error_rows` |
| Gate | `test_clean_run_passes`, `test_run_with_errors_fails`, `test_non_dict_result_is_invalid_and_fails` |
| Sanitation and findings | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_findings_list_coerces_none_and_non_list` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_ok`, `test_headline_errors` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; every artifact-shape (single / multi / generalization /
invalid), malformed-row and non-list branch called out in the spec has an asserting test (lessons
from the Spec 057 / 059 rejections). Expectations are **literal** — e.g. a multi-repo `per_repo` of
`[{"tasks": 3}, {"error": "clone failed", "repo": "a"}]` fixes a finding
`multi.per_repo[a] error: 'clone failed'`, and a corrupt string row fixes
`multi.per_repo[1] malformed row: 'corrupt'` — using values whose `repr` is stable across platforms,
rather than re-deriving them from the module. The only dependency, `artifact_kind`, is exercised
through real single/multi/generalization artifacts (not mocked), so the findings reflect its actual
classification. Integration and CLI coverage stay in `tests/test_run_clean.py`.
