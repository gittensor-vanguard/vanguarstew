# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
