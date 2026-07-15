# Plan 061 — artifact snapshot summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1703

Maps the [spec](./spec.md) onto `benchmark/artifact_snapshot.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_061_artifact_snapshot.py` |
| ------------ | -------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced`, `test_dict_and_is_int_helpers` |
| Numeric semantics | `test_is_number_rejects_bool_and_non_finite` |
| Task total | `test_task_total_top_level_and_per_repo`, `test_task_total_skips_malformed_and_non_finite`, `test_task_total_generalization_sums_partitions` |
| Repo tally | `test_repo_tally_happy_path_and_incoherent` |
| Error flag | `test_has_error_top_level_and_per_repo`, `test_has_error_string_rows_and_falsy` |
| Decisive margin | `test_decisive_margin_top_level_and_judge_report` |
| Snapshot | `test_single_multi_generalization_shapes`, `test_summary_always_includes_required_keys` |
| Snapshot headline | `test_headline_exact_format`, `test_headline_n_a_and_error_status` |
| Pure evaluation | `test_snapshot_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section with explicit malformed / non-finite / empty cases
(lessons from Spec 057 / Spec 059 rejections). Integration and CLI tests stay in
`tests/test_artifact_snapshot.py`.
