# Plan 065 — replay artifact snapshot

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1703

Maps the [spec](./spec.md) onto `benchmark/artifact_snapshot.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_065_artifact_snapshot.py` |
| ------------ | -------------------------------------------------- |
| Numeric helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_is_int_semantics`, `test_dict_helper` |
| Task counting | `test_per_repo_tasks_none_and_non_list`, `test_per_repo_tasks_sums_and_skips`, `test_task_total_prefers_top_level`, `test_task_total_generalization_sums_partitions`, `test_task_total_multi_uses_per_repo` |
| Repo tally | `test_repo_tally_requires_coherent_counts`, `test_repo_tally_rejects_inconsistent_skipped`, `test_repo_tally_shape` |
| Error detection | `test_has_error_top_level`, `test_has_error_generalization_partition`, `test_has_error_multi_per_repo`, `test_single_repo_no_error` |
| Decisive margin | `test_decisive_margin_top_level`, `test_decisive_margin_from_judge_report`, `test_decisive_margin_generalization_uses_tuned`, `test_decisive_margin_none_when_unavailable` |
| Snapshot body | `test_snapshot_keys_are_fixed`, `test_snapshot_coerces_non_dict`, `test_snapshot_masks_wrong_typed_fields`, `test_snapshot_repos_generalization_and_multi` |
| Headline | `test_headline_format`, `test_headline_masks_non_numeric_and_non_dict` |
| Pure evaluation | `test_snapshot_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / wrong-shape / missing-field branch
called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections). Values
are pinned as **literals** — e.g. a `per_repo` of `[{"tasks": 3}, "oops", {"tasks": 2}]` fixes
`tasks` at `5`, and an inconsistent `skipped` fixes `repos` at `None` — rather than re-derived by
calling the module inside the test, so a silent contract change is caught here instead of masked.
Broader coverage stays in `tests/test_artifact_snapshot.py`.
