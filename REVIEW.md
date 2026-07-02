# Review & Contribution Scoring

This document is the contract for how contributions are reviewed and merged. The goal is a
process that is **objective, transparent, consistent, auditable, and reproducible** — so you
can predict the outcome before you open a PR, and every decision leaves a public trail.

## The pipeline

A contribution passes through three gates, in order:

### 1. Automated gates (deterministic — a machine decides, not a person)

Every PR must pass, and you can reproduce all of it locally:

```bash
ruff check .
VANGUARSTEW_OFFLINE=1 python -m pytest -q --cov=agent --cov=benchmark --cov-fail-under=75
```

- **Lint** — `ruff check .` clean.
- **Tests + coverage** — the suite passes and total coverage stays at or above the floor (75%).
- **PR integrity** (see `.github/workflows/pr-integrity.yml`):
  - the PR body references an issue (e.g. `Fixes #12`);
  - no AI-attribution content;
  - the diff is non-trivial;
  - code changes under `agent/` or `benchmark/` ship a test change under `tests/`;
  - the author is within the open-PR limit.

If a gate is red, the PR is not mergeable — there is no human override that skips it.

### 2. Scope gate

A PR must map to an **open issue or milestone**. Out-of-scope work is closed with a pointer
to the [issues](https://github.com/gittensor-vanguard/vanguarstew/issues); start there (look
for `good first issue` / `help wanted`). This keeps effort aimed at real, wanted work.

### 3. Human review (against a published rubric)

Reviewed by a code owner (see `.github/CODEOWNERS`) on the same axes every time, in this
priority order:

| Weight | Criterion | What it means |
| ------ | --------- | ------------- |
| High   | Correctness & tests | Does it do what it claims? Is it covered by a test that would fail without the change? |
| High   | Scope fit | Does it address the referenced issue without unrelated churn? |
| Medium | Quality & clarity | Readable, consistent with surrounding code, no dead code. |
| Medium | Real-behavior proof | The PR shows it actually works (a run, output, or command), not just a claim. |

Decisions are communicated with **status labels** that state the reason (e.g. `needs-tests`,
`out-of-scope`, `accepted`) in the PR thread, so the rationale is always on the record.

## Rejections

Common reasons a PR is closed rather than merged: no linked issue, out of scope, missing
tests, trivial/no-op diff, duplicated or plagiarized work, or AI-attributed content.

## Disagree with a decision?

Reply in the PR thread or open a discussion. Decisions are made against this rubric, not by
preference — if a call looks inconsistent with what's written here, say so and it will be
revisited.

## Where this is going

vanguarstew is itself a contribution-scoring engine (an objective anchor plus a pairwise
judge over real history). Over time, the same tooling will help score incoming contributions
here — holding contributions to the same measurable bar the project is built around.
