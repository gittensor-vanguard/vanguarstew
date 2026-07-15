# vanguarstew — project constitution

Durable project-wide rules. Every agent, contributor, and CI check operates under these.
Edit this file when policy changes; code, tests, and CI follow.

## Agent contract (M0)

- The system shall expose `solve(repo_path, request, ...)` as the single entrypoint.
- The system shall accept `api_base`, `api_key`, and `model` as managed-inference parameters.
- WHEN `VANGUARSTEW_OFFLINE=1` THE system SHALL use a deterministic offline stub.
- Agent files are declared in `vanguarstew_agent_files.json` — only those files are scored.

## Benchmark integrity (M1–M3)

- IF the LLM emits a non-string field where a string is expected THEN the scoring pipeline SHALL coerce and log a warning, not crash.
- IF a repo contributes zero tasks to a multi-repo composite THEN the system SHALL exclude it from aggregation.
- The system SHALL NOT let a forward-looking signal leak through the freeze boundary.
- Held-out repos SHALL be scored in a separate generalization pass, not in the tuned pass.

## Code quality

- The system shall reject PRs that lower test coverage below 75%.
- WHEN code changes under `agent/` or `benchmark/` THEN the PR SHALL include or update tests under `tests/`.
- `ruff check .` and `VANGUARSTEW_OFFLINE=1 python -m pytest -q` SHALL pass before merge.

## Contributors

- WHILE a contributor has >2 open PRs THEN CI SHALL block new PRs from that author.
- WHEN a contributor opens a PR against `main` THEN CI SHALL auto-close with a test-branch redirect.
- PRs SHALL reference at least one issue (e.g. `Fixes #N`).
- Commits SHALL NOT carry AI co-authorship or attribution markers.
- Contributors SHALL target the `test` branch. The maintainer promotes `test` → `main`.

## Scoring (gittensor SN74)

- `perf:*` labels, earned only from a measured benchmark delta, SHALL be the sole source of
  multiplier tiers for `agent/` PRs. Every other surface SHALL carry the flat
  `mult:contribution`. An unlabeled merged PR earns zero (`default_label_multiplier` is `0.0`).
- The subnet's `master_repositories.json` entry for this repo SHALL be the authority for every
  multiplier value; the docs mirror it and lose to it on any disagreement.
- The 3-axis rubric (repo, maintainer, legibility) SHALL feed into emission weight.
