# Spec 083 — replay orchestrator

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1996
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Agent contract (M0)* and *Benchmark integrity
  (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/runner.py`](../../benchmark/runner.py) (the module under test),
  [`specs/001-solve-contract`](../001-solve-contract/spec.md) (the `solve` entrypoint it loads),
  [`specs/005-repo-set`](../005-repo-set/spec.md) (the repo sets it materializes),
  [`specs/077-benchmark-taskgen`](../077-benchmark-taskgen/spec.md) (the tasks it replays),
  [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) and
  [`specs/004-pairwise-judge`](../004-pairwise-judge/spec.md) (the scoring it calls),
  [`specs/069-benchmark-generalization-gate`](../069-benchmark-generalization-gate/spec.md) (the
  gate over its generalization output)

This spec makes the **existing, implicit** orchestration contract explicit. It describes the
as-built behavior of `benchmark/runner.py`; it introduces **no behavior change**.

## Why

`runner.py` is the last module on the freeze → taskgen → runner spine without a spec, and the only
one that defines the **artifact shape** the rest of `benchmark/` agrees on. Roughly forty gate,
integrity and outlook modules read `composite_mean`, `composite_parts`, `scored_repos`, `skipped`,
`per_repo[].error`, `tasks`, `judge_report` and `generalization_gap` — and each of them
independently re-derived rules this module never wrote down. The "unscored placeholder `0.0`"
class of bug is the clearest symptom: an aggregate with nothing scored publishes a perfect-looking
zero, and every consumer had to rediscover that on its own.

## Constants

- `_JUDGE_COMPONENT` SHALL be `{"challenger": 1.0, "tie": 0.5, "baseline": 0.0}` — the
  challenger-perspective judge outcome per row, mirroring `score._JUDGE_OUTCOME`.
- `CLONE_TIMEOUT_SECONDS` SHALL be `300`.
- `WEIGHT_SWEEP_GRID` SHALL be `((0.2, 0.8), (0.4, 0.6), (0.5, 0.5), (0.6, 0.4), (0.8, 0.2))`.

## Acceptance criteria (EARS)

### Agent entrypoint (`load_solve`)

- IF `agent_file` is not an existing regular file THEN it SHALL raise `RuntimeError`
  (`"agent file {path!r} does not exist or is not a regular file"`) — never a bare `OSError` or an
  import traceback.
- IF the file cannot produce an import spec THEN it SHALL raise `RuntimeError`
  (`"cannot load agent file {path!r}: unsupported file type or missing loader"`); IF executing the
  module raises THEN it SHALL raise `RuntimeError` (`"cannot load agent file {path!r}: {exc}"`)
  chained from the original.
- IF the loaded module has no **callable** `solve` THEN it SHALL raise `RuntimeError`
  (`"agent file {path!r} does not define a callable 'solve' entrypoint"`).
- OTHERWISE it SHALL return the module's `solve`. As a side effect it SHALL prepend the agent
  file's directory to `sys.path` when not already present, so a miner agent can import its own
  siblings; the mutation happens only once the file exists.

### Judged submission (`_submission`)

- It SHALL project an agent result onto exactly `{"philosophy", "plan", "rationale"}`, dropping
  every other key, so the judge never sees fields outside the judged view.
- A non-dict result SHALL yield that shape with all three values `None` rather than raising.

### Repo-source materialization (`_materialize_repo_source`)

- IF the source is a placeholder (`OWNER/...`) THEN it SHALL raise `RepoSetError` naming the
  placeholder, before any network access.
- WHEN the source is an existing directory THEN it SHALL return `(source, False)` — a local repo is
  used in place and never removed.
- IF the source is not local AND `checkout_root` is `None` THEN it SHALL raise `RepoSetError`
  (`"repo-set source not found locally: …"`).
- OTHERWISE it SHALL `git clone -q -- <source> <dest>` into
  `checkout_root/repo_{len(os.listdir(checkout_root))}` with `timeout=CLONE_TIMEOUT_SECONDS`, and
  return `(dest, True)`. `--` ends option parsing so a source beginning with `-` is never read as a
  git flag. A timeout SHALL raise `RepoSetError` naming the bound; a clone failure SHALL raise
  `RepoSetError` carrying the stripped stderr.
- The returned `True`/`False` flag is **advisory only**: `run_multi_replay` stores it as
  `selected[i]["cleanup"]` and thereafter only *excludes* it from the per-repo metadata. No code
  path acts on it — clones are removed solely by deleting `checkout_root`. It is documented here as
  dead weight rather than a live guarantee, so a future change that stops removing `checkout_root`
  wholesale cannot mistake it for one.

### Single-repo replay (`run_replay`)

- WHEN `generate_tasks` yields no tasks THEN it SHALL return exactly
  `{"error": "no usable tasks (repo too small for horizon/min_history)", "tasks": 0}` — the
  zero-task shape every aggregate gate keys off.
- Each task SHALL be frozen into `work_dir/task_{k}` (a pre-existing directory is removed first);
  the temp base SHALL be removed in a `finally` **only when `work_dir` was not supplied** by the
  caller.
- The request SHALL be `"plan the maintainer actions for the next {horizon_days} days"` when
  `horizon_days` is truthy, else `"plan the next {horizon} maintainer actions"`.
- IF `solve` returns a non-dict THEN it SHALL be degraded to `{}` rather than crashing the replay.
- Each row SHALL carry `task`, `freeze` (the freeze commit truncated to 10 characters), `winner`
  (`"challenger"` / `"baseline"` / `"tie"`), `judge_order`, `overlap`, `objective` and `composite`.
- The result SHALL carry `tasks`, `baseline`, `tally`, `decisive_margin`
  (`tally["challenger"] - tally["baseline"]`), `composite_mean`, `composite_parts`
  (`judge_mean` / `objective_mean`), `foresight`, `weights`, `rows`, `judge_order_stats`,
  `judge_report`, `offline`, `github_enriched` and `judge_dual_order`.
- Every mean SHALL be rounded to 3 places, and SHALL be `0.0` — not `None` — over an empty list.

### Weight sweep (`weight_sweep`)

- It SHALL re-blend already-scored rows at each `(w_judge, w_objective)` in `grid` without
  re-running the replay, returning `{"w_judge", "w_objective", "composite_mean"}` **in grid order**.
- Per task the blend SHALL mirror `score.composite_score` exactly: normalize by the weight sum,
  round each task's composite to 3 places, then average and round again — so sweeping at a run's own
  weights reproduces that run's reported `composite_mean`.
- A non-list `rows` SHALL be treated as empty **with a warning**; a non-dict row SHALL be skipped
  **with a warning**; a `None` row SHALL be skipped **silently**.
- A row whose `winner` is not a `_JUDGE_COMPONENT` key (including a missing one) SHALL be skipped
  **silently** — no warning, unlike the non-dict case. A falsy `objective` SHALL be read as `{}`.
- WHEN no row scores THEN every grid entry SHALL report `composite_mean` `0.0`.
- IF a grid entry's weights sum to zero THEN the sum SHALL fall back to `1.0`, so the entry reports
  `0.0` rather than raising `ZeroDivisionError`.

### Multi-repo aggregation (`run_multi_replay`)

- IF `repos` and `repo_set` are both given, or neither, THEN it SHALL raise `ValueError`
  (`"pass exactly one of 'repos' or 'repo_set'"`).
- WHEN a `repo_set` is given THEN the partition SHALL be `repo_set_partition` when truthy, else
  `"held_out"` when `held_out`, else `"tuned"`; an empty partition SHALL raise `RepoSetError`. The
  result SHALL then carry `repo_set` = `{"path", "name", "selection"}`.
- A `checkout_root` temp dir SHALL be created for a repo-set run and removed on **both** paths: a
  `BaseException` during the materialization loop SHALL remove it before re-raising, and the replay
  loop's `finally` SHALL remove it otherwise. Neither path may leak already-cloned repos.
- Each entry's `freeze_window` SHALL override the shared kwargs for that repo only, via
  `_freeze_window_dict` (a non-dict is ignored **with a warning**).
- IF `run_replay` raises `RuntimeError` for a repo THEN it SHALL be logged and recorded as
  `{"error": str(exc), "tasks": 0}` so one bad repo can neither abort the batch nor enter the mean.
  Other exception types are not caught here.
- `per_repo[i]` SHALL be `{**meta, **res}` — the replay result **wins** on any key collision with the
  repo-set metadata — where `meta` is the selection entry minus `repo_path` and `cleanup`.
- `tally` SHALL accumulate over **every** repo (a falsy `tally` contributes nothing), while the
  composite aggregation SHALL be gated on `res["tasks"] > 0`, so a short or errored repo is counted
  in `skipped` and excluded from the mean.
- The result SHALL carry `repos` (`len(per_repo)`), `scored_repos` (the gated count), `skipped`
  (their difference), `composite_mean`, `composite_parts`, `foresight`, `judge_order_stats`,
  `judge_report` and `per_repo`.
- **Unscored placeholder:** WHEN nothing scored THEN `scored_repos` SHALL be `0` and
  `composite_mean` SHALL be `0.0` — **not** `None`. The pair `(scored_repos == 0,
  composite_mean == 0.0)` is the placeholder signal every downstream consumer must mask; it is a
  deliberate contract, not a real score.

### Generalization report (`run_generalization_report`)

- It SHALL run the `tuned` and `held_out` partitions of one repo set and return
  `{"repo_set", "tuned", "held_out", "generalization_gap"}`.
- IF a partition raises `RepoSetError` THEN it SHALL be recorded as
  `{"error": str(exc), "scored_repos": 0, "composite_mean": 0.0}` rather than aborting the report.
  Only `RepoSetError` is caught: any other exception propagates, despite the docstring's broader
  "recorded with its error" wording.
- `generalization_gap` SHALL be `round(tuned["composite_mean"] - held_out["composite_mean"], 3)`
  only when **both** partitions have a truthy `scored_repos`; otherwise it SHALL be `None`, so the
  gap is never reported from a single side.

### Helper coercions

- `_rows_list(rows, field)` and `_sweep_rows(rows)` SHALL return `rows` when it is a list, else `[]`
  — warning for a non-`None` non-list, silent for `None`. `_sweep_rows` SHALL warn under the field
  name `"weight_sweep rows"`.
- `_freeze_window_dict(freeze_window, field)` SHALL return it when it is a dict, else `{}` — warning
  for a non-`None` non-dict, silent for `None`.

## Out of scope

- The internals of `generate_tasks` (Spec 077), `write_frozen` / `scrub_context`, `judge_verbose`
  (Spec 004), `objective_score` (Spec 002) and the baseline opponents — each has, or is getting,
  its own spec. This spec pins how the runner *composes* them and what it publishes.
- Actual git clones and network access; no test performs either.
- Correcting any of the divergences catalogued above (the dead `cleanup` flag, the placeholder
  `0.0`, the silent unrecognized-`winner` skip, the `RepoSetError`-only catch); each is a behavior
  change and belongs in its own issue.

## Verification

- `tests/test_spec_083_runner.py` exercises each EARS block above with **literal** expected values,
  using in-memory fakes for `run_replay` / `solve` and `tmp_path` for the loader, so no test clones
  a repo or touches the network.
- Broader behavioral coverage remains in `tests/test_runner.py` and `tests/test_multi_repo.py`.
