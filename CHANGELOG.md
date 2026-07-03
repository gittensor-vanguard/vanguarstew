# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Maintainer-assist mode (`agent/review.py`, `scripts/review_pr.py`): the same agent the
  benchmark scores, applied to a **live** PR — it reads the PR and outputs a maintainer review
  (recommended action, best-fit `mult:*` value tier, scope/tests checks, concerns, advice).
  This is the "how it helps a maintainer" side: real triage/review assistance, not just scoring.
- Composite score: the pairwise judge (trajectory + decision process) and the objective anchor
  (module recall, release/bump correctness) are now blended into a single per-task and mean
  score in [0, 1], with tunable weights (`--w-judge` / `--w-objective`, default 0.6 / 0.4).

### Fixed
- Judge robustness: the offline pairwise stand-in ranked submissions by raw plan **length**,
  so a plan padded with empty-of-substance items could beat a shorter, substantive one. It now
  ranks by the count of items that actually name something (non-empty `title`/`theme`), so
  length alone can't win over substance (#54).
- Objective anchor: `release_signaled`/`release_predicted` no longer fire on an incidental
  version mentioned mid-subject (e.g. `chore(deps): bump lodash to v4.17.21`, `fix crash in
  v1.2.0 parser`). Release detection now requires explicit release wording or a version-tag
  subject, so dependency bumps no longer inflate the release-prediction signal (#57).

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
