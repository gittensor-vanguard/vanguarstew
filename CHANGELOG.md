# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Leakage: `agent/context.py::_context_from_git` (the fallback context builder used when
  `.vanguarstew_context.json` is absent) now filters tags with `--merged HEAD`, so a tag
  reachable only from an unmerged branch can no longer leak into `releases` as knowable-at-T.
  Mirrors the reachability guard `benchmark/freeze.py::build_context` already applies (#256).
- `agent/philosophy.py::infer_philosophy` now coerces a non-dict LLM response (e.g. a
  top-level JSON array) back to the offline stub, mirroring the guard already used by
  `decider.decide` and `review.review_pr`. Previously a substantive-but-list philosophy
  silently forfeited the offline judge's `philosophy_signal` tiebreaker (#190).
- Benchmark hygiene: `benchmark/taskgen.py::revealed_window` now parses changed-file
  lists from NUL-delimited `git show --name-only -z` output via a reusable
  `benchmark.freeze.parse_path_list` helper, instead of whitespace `.split()`. Filenames
  containing spaces or shell-sensitive characters are no longer corrupted (which would
  mis-attribute file-weighted scoring); first-parent merges still yield an empty file
  list as before. Adds `tests/test_taskgen.py` regression coverage (#137).

## [0.3.0] - 2026-07-03

### Added
- Objective anchor: open-issue **backlog recall** (`benchmark/score.py`) — when frozen
  `open_issues` are knowable at T, `objective_score` reports `backlog_recall`,
  `addressed_issue_numbers`, and `matched_issue_numbers`, scoring whether a plan anticipated
  issues the revealed window actually addressed (title ↔ commit-subject overlap). Also reports
  `addressed_backlog_diagnostics` — the issue number, title, and matched commit subject behind
  each addressed issue — for maintainer-facing inspection; purely additive, doesn't change
  scoring. Git-only runs or an empty backlog degrade gracefully (#44, #135).
- Generalization (M3): **multi-repo replay** — `run_multi_replay` / `scripts/run_eval.py --repos`
  runs several repos and averages each repo's own `composite_mean` into one cross-repo number
  (per-repo results retained; too-small repos skipped), so the agent is scored on breadth rather
  than a single tuned repo (#51).
- Generalization (M3): **leakage-safe repo-set config + loader** (`benchmark/repo_set.py`,
  `benchmark/repo_sets/`) — the replay repo list is a checked-in, strictly-validated JSON config
  (recent/obscure tier, `held_out`, freeze-window hints) instead of a hardcoded array, so the
  curated selection is reviewable and versioned (#55).
- Composite: **file-weighted module recall** now feeds the composite score — the objective anchor
  weights modules by how much of the revealed maintainer effort landed in each, so the blended
  score better reflects where the work actually concentrated (#91).
- Judge integrity: the pairwise judge now defends against LLM **position bias** with dual-order
  consistency — it asks both presentation orders and awards a win only if it survives the swap,
  otherwise a tie. A position-biased judge can no longer earn a spurious win, and per-task
  variance drops. Default on; opt out via `run_replay(dual_order_judge=False)` /
  `--single-order-judge`; the replay result reports `judge_dual_order` (#87).
- Planner queue reconciliation (`agent/planner.py`): a deterministic pass makes the plan honor
  the open-PR queue even when the LLM disregards it — an item that restates an open PR's work
  is down-weighted to a `triage` review item and flagged with `restates_pr`, redundant items
  targeting the same PR are collapsed, and if the plan ignores the queue entirely a review
  item for the top PR is prepended. Keeps the output coherent and de-duplicated regardless of
  model quality (#68).
- Development backend: `tools/codex_llm.py`, an optional `agent.llm.LLM`-compatible LLM backed
  by the local `codex` CLI (ChatGPT / OAuth, e.g. gpt-5.5), for running the benchmark and
  maintenance tooling **without an API key**. Dev/ops only — it is deliberately kept out of the
  scored `agent.solve` path, which still uses only validator-supplied inference per the
  managed-inference contract (`agent/llm.py`).
- Objective scoring: **commit-kind recall** (`benchmark/score.py`) — `objective_score` now
  reports `kind_recall`, `actual_kinds`, and `matched_kinds`, grading whether a plan
  anticipated the *kind* of maintainer work (feat/fix/docs/refactor/…/release) that the
  revealed window actually did, parsed deterministically from Conventional-Commit subjects
  (#41).
- Maintainer-assist mode (`agent/review.py`, `scripts/review_pr.py`): the same agent the
  benchmark scores, applied to a **live** PR — it reads the PR and outputs a maintainer review
  (recommended action, best-fit `mult:*` value tier, scope/tests checks, concerns, advice).
  This is the "how it helps a maintainer" side: real triage/review assistance, not just scoring.
- Composite score: the pairwise judge (trajectory + decision process) and the objective anchor
  (module recall, release/bump correctness) are now blended into a single per-task and mean
  score in [0, 1], with tunable weights (`--w-judge` / `--w-objective`, default 0.6 / 0.4).
- Objective anchor: semver-aware release-bump scoring — when a genuine release appears in the
  revealed window, `objective_score` derives the actual bump level (major/minor/patch) from
  the semver delta between the frozen base version and the released version, and reports
  `bump_actual` / `bump_match` against the agent's predicted `version_bump` (tags with or
  without a leading `v`, and missing-patch/pre-release forms, all parse). The released version
  is read only from genuine release subjects, so a dependency bump can't skew the bump level.

### Fixed
- Planner PR matching (`agent/planner.py`): when several open-PR titles are quoted in a
  plan and one nests inside another (e.g. `Add streaming export` inside `Add streaming
  export docs`), `_matched_pr` now prefers the longest matching title instead of the first
  in queue order, so the more specific PR wins regardless of queue order. Explicit `#N`
  references still take priority (#104).
- Judge robustness (follow-up to #54): the offline substance heuristic keyed only on
  `title`/`theme` *presence*, so a plan stuffed with generic filler titles (`misc`, `updates`,
  `various`, …) could still out-rank a shorter, concrete one. Substance is now a weighted score
  — filler/blank items count for nothing, and each structured action field (`kind`, `files`,
  per-item `rationale`) beyond a real title adds weight — so length/filler never beats
  substance (#70).
- Judge robustness: the offline pairwise stand-in ranked submissions by raw plan **length**,
  so a plan padded with empty-of-substance items could beat a shorter, substantive one. It now
  ranks by the count of items that actually name something (non-empty `title`/`theme`), so
  length alone can't win over substance (#54).
- Objective anchor: `release_signaled`/`release_predicted` no longer fire on an incidental
  version mentioned mid-subject (e.g. `chore(deps): bump lodash to v4.17.21`, `fix crash in
  v1.2.0 parser`). Release detection now requires explicit release wording or a version-tag
  subject, so dependency bumps no longer inflate the release-prediction signal (#57).
- Task generation: `revealed_window` (`benchmark/taskgen.py`) reported **zero changed files**
  for merge commits (a plain `git show` of a clean merge yields an empty combined diff),
  silently depressing module-recall scoring for any repo that merges via PRs (#113). It also
  split file lists on whitespace, corrupting attribution for paths containing spaces (#116).
  Both are fixed by diffing merges against their first parent and splitting on lines instead.
  Regression coverage added in `tests/test_taskgen.py` via a reusable merge-history fixture
  (#117).
- Leakage: frozen milestone `state` is now computed as-of-T from `closed_at` instead of copying
  the milestone's present-day state, so a milestone that existed at T but was closed *after* T
  is no longer leaked into the context as completed (#77).

## [0.2.0] - 2026-07-03

### Added
- M2: robust judge winner parsing — tolerant to truncated/verbose model output (found via
  live verification against a real model).
- M2: leakage — also scrub GitHub release `name` fields in the frozen context.
- M2: maintainer-philosophy inference now uses few-shot examples for steadier, more
  evidence-based output (#33, thanks @real-venus).
- M2: selectable reference baselines for the pairwise judge — a deterministic `heuristic`
  opponent (continue dominant themes + clear the backlog) alongside `empty`, via `--baseline`
  (#34, thanks @real-venus).
- Auto-label workflow: applies organizational **area/type** labels (agent/benchmark/leakage/
  tests/ci/docs; enhancement/bug/refactor/chore) from changed paths and the PR title. Never
  touches `mult:*` value multipliers — those stay maintainer-applied.
- CI split into focused jobs (**lint** / **validate** / **test**), with a new config-validation
  step that parses every workflow YAML and JSON config.
- M2: GitHub issue/PR fetch now paginates back toward the freeze time T (bounded, with an
  `_issues_truncated` flag), so open-at-T reconstruction is complete regardless of how old T
  is — not just the newest page.
- M2: leakage hardening — forward-reference scrubbing (mask `#N` back-references, GitHub
  issue/PR/commit links, and raw SHAs in the frozen context) and recent-window + deterministic
  rotation for freeze-point selection (`--recent-bias`, `--rotation-seed`).
- M2: the pairwise judge now evaluates the **decision process** — the agent's inferred
  maintainer philosophy and reasoning are passed to the judge and weighed alongside
  trajectory/direction match, so when two plans point the same way the sounder reasoning wins.
- Trustable contribution pipeline: a published review/scoring rubric (`REVIEW.md`), a
  PR-integrity check (issue reference, no AI-attribution, non-trivial diff, tests-with-code,
  per-author PR limit), `CODEOWNERS` review routing, and a CI coverage floor.

## [0.1.0] - 2026-07-02

### Added
- M2 (start): objective scoring anchor — a deterministic, structural signal that grades a
  plan against ground truth from the revealed window (which top-level modules actually
  changed; whether a release happened), reported per task alongside the pairwise judge.
- M1: GitHub-API context enrichment — freeze-time snapshots can now include the maintainer's
  real working surface (open issues, open PRs, labels, milestones, releases) reconstructed as
  of time T, with strict "knowable at T" filtering. Enabled with `--enrich`; degrades to
  git-only context when offline.
- M0 scaffold: maintainer agent with a fixed `solve()` entrypoint (philosophy → plan →
  decide → implement) and an OpenAI-compatible managed-inference client with an offline mode.
- Time-travel replay benchmark: freeze a repo at a point in time, generate tasks from git
  history, and score plans with a pairwise LLM judge.
- Open-source project scaffolding: license, contributing guide, code of conduct, security
  policy, issue/PR templates, and CI.

## [0.0.1] - 2026-07-01

- Initial project structure.
