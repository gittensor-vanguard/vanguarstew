# Plan 086 — replay orchestrator

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1996

Maps the [spec](./spec.md) onto `benchmark/runner.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_086_runner.py` |
| ------------- | ---------------------------------------- |
| Agent entrypoint loading | `test_load_solve_missing_file_message`, `test_load_solve_directory_message`, `test_load_solve_exec_error_wraps_original`, `test_load_solve_missing_entrypoint_message`, `test_load_solve_inserts_agent_dir_into_sys_path_once` |
| Judged-submission projection | `test_submission_projects_exactly_three_keys`, `test_submission_non_dict_returns_none_triple` |
| Repo-source materialization | `test_materialize_placeholder_raises_regardless_of_checkout_root`, `test_materialize_local_dir_returns_false_and_ignores_checkout_root`, `test_materialize_missing_root_raises`, `test_materialize_clone_success_returns_true`, `test_materialize_clone_timeout_raises_repo_set_error`, `test_materialize_clone_failure_raises_with_stderr`, `test_materialize_cleanup_flag_is_never_read_back` |
| Single-repo replay artifact | `test_run_replay_solve_fn_overrides_agent_file`, `test_run_replay_solve_fn_type_error`, `test_run_replay_empty_tasks_shortcut_shape`, `test_run_replay_non_dict_challenger_degrades_to_empty`, `test_run_replay_row_keys_and_winner_decode`, `test_run_replay_full_key_set`, `test_run_replay_decisive_margin_excludes_ties`, `test_run_replay_work_dir_supplied_is_not_removed` |
| Weight sweep | `test_weight_sweep_scored_set_requires_dict_and_known_winner`, `test_weight_sweep_non_dict_row_warns_and_skips`, `test_weight_sweep_bad_winner_dict_row_skips_silently`, `test_weight_sweep_zero_sum_weights_do_not_raise`, `test_weight_sweep_empty_scored_set_all_zero`, `test_weight_sweep_matches_composite_score_at_run_weights` |
| Multi-repo aggregation | `test_run_multi_replay_requires_exactly_one_of_repos_or_repo_set`, `test_run_multi_replay_partition_selection_precedence`, `test_run_multi_replay_empty_selection_raises_before_checkout_root`, `test_run_multi_replay_materialization_failure_cleans_checkout_root`, `test_run_multi_replay_per_repo_merge_precedence`, `test_run_multi_replay_runtime_error_isolated_as_zero_task_repo`, `test_run_multi_replay_other_exception_types_propagate`, `test_run_multi_replay_tasks_gate_excludes_from_mean_and_scored_repos`, `test_run_multi_replay_tally_sums_across_all_repos_regardless_of_scoring`, `test_run_multi_replay_unscored_batch_reports_zero_placeholders`, `test_run_multi_replay_repo_set_meta_present_only_for_repo_set_path`, `test_run_multi_replay_checkout_root_removed_after_loop` |
| Generalization report | `test_run_generalization_report_catches_only_repo_set_error`, `test_run_generalization_report_other_exceptions_propagate`, `test_run_generalization_report_gap_requires_both_sides_scored`, `test_run_generalization_report_result_key_set` |

## Verification strategy

Each EARS section is exercised at the narrowest layer that reaches it, so the suite runs with no
network access and clones no real repository:

- **`load_solve`** and **`_materialize_repo_source`** touch the filesystem directly (a loadable
  `agent.py`-shaped file, a fake `git` via `monkeypatch.setattr("benchmark.runner.subprocess.run",
  ...)`) — the same style `tests/test_runner.py` already uses for
  `test_clone_timeout_raises_clean_repo_set_error` and siblings. No real clone ever runs.
- **`weight_sweep`** takes plain dict rows built by hand; no repo, no `run_replay` call, no LLM.
- **`run_replay`**'s contract points that don't depend on judge/objective internals (the empty-task
  shortcut, the non-dict-challenger degrade, `solve_fn` override and type-checking, the full key
  set, `decisive_margin`, `work_dir` handling) are exercised with `solve_fn` stubs returning fixed
  dicts over a two-commit throwaway git repo (`_dated_repo`-style, minimal history so
  `generate_tasks` yields exactly one task) — `VANGUARSTEW_OFFLINE=1` keeps the judge deterministic
  with no network call. Judge/objective correctness itself is out of scope (Specs 002/004);
  `tests/test_runner.py` already covers `run_replay`'s realistic end-to-end shape.
- **`run_multi_replay`** and **`run_generalization_report`**'s aggregation, merge-precedence,
  error-isolation, and gating rules are exercised by monkeypatching
  `benchmark.runner.run_replay` with an in-memory fake that returns scripted per-repo dicts
  (including one that raises `RuntimeError` and one that raises a different exception) — this
  isolates the orchestration contract from the expensive real replay path entirely, matching the
  "in-memory fakes, no network, no clones" verification the issue calls for. The `repos=` list path
  is used where a real `repo_set` config isn't needed (partition selection, empty-selection,
  materialization-failure cleanup use a hand-built `RepoSet`/`RepoEntry` instead of a JSON file on
  disk).
- Literal expectations (exact key sets, exact messages/substrings, exact merge results) are pinned
  directly rather than re-derived by calling the module twice, so a silent contract change is
  caught here instead of masked.
