# Plan 077 — replay task generation

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1952

Maps the [spec](./spec.md) onto `benchmark/taskgen.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_077_taskgen.py` |
| ------------ | ---------------------------------------- |
| History enumeration | `test_commit_dates_full_sha_keys_oldest_to_newest` (first-parent ordering itself is pinned in `tests/test_taskgen.py`) |
| Reference records | `test_commit_detail_shape_and_sha_prefix` |
| Commit-count window | `test_revealed_window_starts_after_freeze_and_truncates` |
| Time window | `test_revealed_window_days_includes_commit_landing_exactly_at_cutoff`, `test_revealed_window_days_stops_at_first_chronology_break` |
| Window occupancy | `test_window_commit_count_prefix_scan_and_guards` |
| Time-spaced picks | `test_space_picks_days_strict_spacing_fixed_grid_and_honesty`, `test_time_horizon_seeded_rotation_may_drop_sparse_pool_picks` |
| Date parsing | `test_as_dt_normalizes_and_rejects`, `test_as_date_truncates_and_raises_on_malformed` |
| Usable indices | `test_commit_horizon_usable_rule_stride_and_task_shape`, `test_commit_horizon_empty_usable_returns_empty_list`, `test_time_horizon_usable_rule_and_task_shape`, `test_time_horizon_without_full_forward_history_returns_empty`, `test_time_horizon_excludes_freezes_whose_window_holds_no_work`, `test_time_horizon_forward_history_boundary_is_inclusive`, `test_horizon_days_zero_falls_back_to_commit_mode`, `test_date_bounds_are_inclusive_on_both_ends`, `test_date_bounds_apply_in_time_mode_too` |
| Pool and picks | `test_commit_horizon_rotation_seed_sample`, `test_recent_bias_draws_from_last_three_n_usable` |
| Task shape | `test_commit_horizon_usable_rule_stride_and_task_shape`, `test_time_horizon_usable_rule_and_task_shape` |

## Verification strategy

One contract-test group per EARS section, over tiny throwaway git repos built with pinned
`GIT_COMMITTER_DATE`/`GIT_AUTHOR_DATE` stamps (same `_dated_repo` conventions as
`tests/test_taskgen.py`: noon-UTC commits, `gc.auto 0`, `commit.gpgsign false`). Expected freeze
indices, revealed subjects, counts, and per-mode key sets are pinned as **literal** values —
e.g. 12 daily commits with `min_history=2, horizon=5` fixes the usable pool at `[2..6]` and the
unseeded picks at `[2, 3, 4]` — rather than re-derived by calling the module, so a silent
selection-rule change is caught here instead of masked. SHAs are dynamic, so SHA-adjacent
expectations pin structure and relationships (prefix length 10, `freeze_commit ==
commits[freeze_index]`) instead of literal digests. The pure helpers
(`_window_commit_count`, `_space_picks_days`, `_as_date`, `_as_dt`) are exercised with synthetic
inputs, no repo needed. The one seed-dependent literal (a seeded sparse-pool run yielding zero
picks) rests only on `random.Random(seed).random()`, the sequence CPython guarantees stable
across versions. Merge-attribution and NUL path-parsing coverage stays in
`tests/test_taskgen.py`.
