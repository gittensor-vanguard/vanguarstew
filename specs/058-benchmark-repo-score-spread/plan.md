# Plan 058 — repo score spread summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1616

Maps the [spec](./spec.md) onto `benchmark/repo_score_spread.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_058_repo_score_spread.py` |
| ------------ | -------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty`, `test_is_int_semantics` |
| Numeric semantics | `test_is_number_rejects_bool_and_non_finite` |
| Per-repo scores | `test_repo_scores_multi_and_single`, `test_repo_scores_skips_non_numeric` |
| Spread helper | `test_spread_empty_and_populated` |
| Repo score spread summary | `test_multi_artifact_spread`, `test_generalization_partitions`, `test_summary_always_includes_required_keys` |
| Repo score spread headline | `test_headline_exact_format`, `test_headline_no_scored_repos`, `test_headline_n_a_range` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_repo_score_spread.py`.
