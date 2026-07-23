# Plan 083 — replay orchestrator

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1996

Maps the [spec](./spec.md) onto `benchmark/runner.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_083_runner.py` |
| ------------ | ---------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Agent entrypoint | `test_load_solve_rejects_a_missing_file`, `test_load_solve_rejects_a_module_that_fails_to_execute`, `test_load_solve_rejects_a_module_without_a_callable_solve`, `test_load_solve_returns_the_entrypoint_and_extends_sys_path` |
| Judged submission | `test_submission_projects_only_the_judged_view`, `test_submission_degrades_a_non_dict_result` |
| Repo-source materialization | `test_materialize_rejects_a_placeholder_source`, `test_materialize_uses_a_local_directory_in_place`, `test_materialize_without_a_checkout_root_fails_closed`, `test_materialize_clones_with_a_bounded_timeout_and_option_terminator`, `test_materialize_maps_a_clone_timeout_and_failure_to_repo_set_error`, `test_materialize_cleanup_flag_is_advisory_only` |
| Single-repo replay | `test_run_replay_zero_task_shape_is_pinned` |
| Weight sweep | `test_weight_sweep_reproduces_the_runs_own_composite_mean`, `test_weight_sweep_preserves_grid_order`, `test_weight_sweep_warns_on_a_non_list_rows`, `test_weight_sweep_warns_on_a_non_dict_row`, `test_weight_sweep_skips_an_unrecognized_winner_silently`, `test_weight_sweep_reads_a_falsy_objective_as_empty`, `test_weight_sweep_with_nothing_scored_is_zero`, `test_weight_sweep_zero_sum_blend_does_not_raise` |
| Multi-repo aggregation | `test_multi_replay_requires_exactly_one_source`, `test_multi_replay_aggregates_only_scored_repos`, `test_multi_replay_records_a_runtime_error_like_a_zero_task_repo`, `test_multi_replay_result_shape_is_pinned`, `test_multi_replay_unscored_aggregate_is_a_zero_placeholder`, `test_multi_replay_replay_result_wins_a_key_collision`, `test_multi_replay_tally_accumulates_over_every_repo` |
| Generalization report | `test_generalization_report_shape_and_gap`, `test_generalization_report_gap_is_none_from_a_single_side`, `test_generalization_report_records_a_repo_set_error_partition`, `test_generalization_report_propagates_a_non_repo_set_error` |
| Helper coercions | `test_rows_list_coercion`, `test_sweep_rows_uses_its_own_field_name`, `test_freeze_window_dict_coercion` |

## Verification strategy

One contract-test group per EARS section; every zero-task / error / skip / malformed / collision
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections and
the finding lists on the closed Spec 068 / 069 PRs). **No test clones a repo or touches the
network**: `run_replay` is replaced with an in-memory fake when the aggregation contract is under
test, `subprocess.run` is monkeypatched when materialization is, and `load_solve` runs against real
files written to `tmp_path`.

Expectations are **literal** — the exact zero-task dict, the exact aggregate key set, exact
`(w_judge, w_objective, composite_mean)` triples — rather than re-derived from the module. The
weight-sweep group pins the *round-trip* property explicitly (sweeping at a run's own `0.6 / 0.4`
weights reproduces its reported `composite_mean`), because that is the guarantee the helper exists
to provide and the one a "simplification" of the double-rounding would break.

Three behaviors get dedicated tests precisely because they look like defects and are in fact the
contract, so a future reader does not "fix" them blind:

- the **unscored placeholder** (`scored_repos == 0` with `composite_mean == 0.0`, never `None`) —
  the signal ~40 downstream gates each re-detect;
- the **silent** skip of a row with an unrecognized `winner`, asserted against the *warned* non-dict
  row in the same group so the asymmetry is explicit rather than accidental;
- the **advisory-only `cleanup` flag** — asserted by showing `_materialize_repo_source` returns it
  and that it never reaches the per-repo metadata, with cleanup instead proven by the `checkout_root`
  removal on both the materialization-failure and the normal paths.

Warning branches are asserted via `caplog` on the `benchmark.runner` logger, and the silent ones
(`None` rows, `None` freeze windows, an unrecognized `winner`) assert the *absence* of a warning so
"silent" is not left untested. Integration coverage stays in `tests/test_runner.py` and
`tests/test_multi_repo.py`.
