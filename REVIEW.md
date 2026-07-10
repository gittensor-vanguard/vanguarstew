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
  - no AI-attribution content in the PR body **or commit messages** (including `Co-authored-by:` trailers for AI assistants);
  - the diff is non-trivial;
  - code changes under `agent/` or `benchmark/` ship a test change under `tests/`;
  - the author is within the open-PR limit (**at most 2 open PRs** per contributor; the maintainer is exempt). Over-limit PRs are **auto-closed** by the `PR limit` workflow (`.github/workflows/pr-limit.yml`) — it keeps your 2 earliest open PRs and closes newer extras, at open time and on a periodic sweep.

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
| High   | Non-redundancy | Does it duplicate existing analysis over the **same data shape**? A new module/metric/report that slices a dict another module already slices, or re-derives a value an existing helper produces, is redundant even when its diff is original and its tests pass. Prefer parametrizing or extending the existing code. Conceptual duplication is rejected the same as literal duplication. |
| Medium | Quality & clarity | Readable, consistent with surrounding code, no dead code. |
| Medium | Real-behavior proof | The PR shows it actually works (a run, output, or command), not just a claim. |

Decisions are communicated with **status labels** that state the reason (e.g. `needs-tests`,
`out-of-scope`, `accepted`) in the PR thread, so the rationale is always on the record.

## Contribution value labels

Once this repo is registered on gittensor, each merged PR's emission weight comes from a
label. Two separate tracks, because "agent got measurably better" and "the harness/tooling
improved" are different claims that need different evidence:

### `perf:*` — agent/ PRs, earned by a measured benchmark delta (SN66-style)

A PR touching `agent/` (the scored, miner-editable surface) earns its label **only** from a
measured improvement — never from a maintainer's read of the diff. This is the same model
[gittensor-ai-lab/sparkinfer](https://github.com/gittensor-ai-lab/sparkinfer) uses for its
`eval:XS`–`eval:XL` real-hardware speedup bands: labels are bot-assigned from an actual
before/after run, and most merged PRs carry no label at all — the bands are rare and mean
something specific.

The maintainer bot runs `scripts/score_pr_delta.py` **twice** — once against the public
`benchmark/repo_sets/curated.json`, once against a private, undisclosed repo set the PR
author has never seen — and combines the two via `combine_dual_target()`, which takes the
**worse** of the two results. A PR can't earn a band by tuning against the repos it can see
while flat-lining or regressing on repos it can't; that's the whole point of the private
target.

| Label | Multiplier | Composite Δ (on the worse target) |
| ----- | ---------- | ---------------------------------- |
| `perf:xl` | ×4.0 | ≥ 0.15 |
| `perf:l`  | ×2.5 | ≥ 0.08 |
| `perf:m`  | ×1.5 | ≥ 0.04 |
| `perf:s`  | ×1.0 | ≥ 0.02 |
| `perf:xs` | ×0.5 | ≥ 0.01 |
| *(none)*  | — | ≤ 0.01 (noise floor) — still mergeable, just no multiplier |

**These thresholds are deliberately rough.** The project has very few real
`score_pr_delta` data points so far — the bands exist to be recalibrated as real
before/after deltas accumulate, not guessed once and frozen. `scripts/score_pr_delta.py`'s
`BAND_THRESHOLDS`/`BAND_MULTIPLIERS` are the single source of truth; this table mirrors
them and must be updated in lockstep if they change.

A regression on either the judge or the objective component (past the noise floor), on
*either* target, is a **hard merge block** — not a label cap. Trading one axis for the
other (sounding better to the judge while the objective anchor quietly drops) counts as a
regression. The author must revise until it clears, or the PR is closed.

Before a band is finalized, the maintainer bot runs an **anti-cheating pass** over the
diff — looking for benchmark-detection branching, hardcoded outputs that match a known
repo/task, disabled assertions, or anything that would make the measured delta not
reflect genuine agent improvement. A PR that trips this check is closed regardless of its
measured number, same as sparkinfer's `flagged:gaming` convention.

CI runs a lightweight offline smoke check on every `agent/`-touching PR
(`agent-benchmark-smoke.yml`) — this catches crashes and output-shape regressions only. It
is **not** the scoring evidence and cannot influence a `perf:*` label or the merge block:
offline mode returns each file's own fixed stub regardless of the prompt, so it cannot
measure whether a PR changed the agent's actual reasoning. The real score-delta is a
maintainer-bot-run live comparison against both repo targets.

### `mult:contribution` — everything else (×0.2)

PRs to `benchmark/`, `tests/`, `docs/`, `.github/`, or any other non-`agent/` surface get a
single flat label, `mult:contribution` (×0.2), on merge — there's no "agent performance"
to measure for harness/tooling work, so it isn't put through the banding pipeline. This
replaces the old graduated `mult:core-correctness`/`capability`/`enhancement`/`maintenance`/
`docs` ladder, which scored a maintainer's *read* of a diff rather than a measured effect —
exactly the gap the `perf:*` system above closes for `agent/`.

- Only labels applied by the maintainer bot (or matedev01) count toward the multiplier.
- Area labels (`agent`, `benchmark`, `leakage`) are organizational only and do **not**
  affect scoring.
- No label ⇒ zero (this repo's `default_label_multiplier` is `0.0`) — matches the *(none)*
  row above for `agent/` PRs with no measurable improvement.

## Rejections

Common reasons a PR is closed rather than merged: no linked issue, out of scope, missing
tests, trivial/no-op diff, duplicated or plagiarized work, **conceptual redundancy** (a new
module/metric that re-derives what existing code already produces over the same data shape —
parametrize or extend instead), AI-attributed content, or (for `agent/` PRs) a
maintainer-bot-run `scripts/score_pr_delta.py` regression (`band: "blocked"` — see § `perf:*`
above) or a flagged anti-cheating finding.

## Disagree with a decision?

Reply in the PR thread or open a discussion. Decisions are made against this rubric, not by
preference — if a call looks inconsistent with what's written here, say so and it will be
revisited.

## Where this is going

vanguarstew is itself a contribution-scoring engine (an objective anchor plus a pairwise
judge over real history). Over time, the same tooling will help score incoming contributions
here — holding contributions to the same measurable bar the project is built around.
