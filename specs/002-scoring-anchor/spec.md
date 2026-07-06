# Spec 002 — the objective scoring anchor

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #494
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (the agent side of the same seam)

This spec makes the **existing, implicit** objective-scoring contract explicit. It describes the
deterministic anchor already implemented in `benchmark/score.py`; it introduces **no behavior
change**. Per the blog: *the revealed git history is the spec, and `score.py` verifies against
it* — this writes that verification contract down.

## Why

An agent's plan is graded two ways: a pairwise **judge** (the differentiator) and a
deterministic **objective anchor** (the un-gameable ground). The anchor is what makes scoring
reproducible and resistant to prose-fluff, because it keys off real changed file paths and
real release/commit facts — not free-text similarity. That contract must be explicit so agent
devs know exactly what earns credit and reviewers can check scoring changes against it.

## User stories

1. **As the validator**, I score an agent's plan against structural ground truth from the
   revealed window, deterministically and offline — so the anchor can't be gamed with fluent
   prose and is reproducible across runs.
2. **As an agent developer**, I know precisely what the anchor rewards (naming the modules that
   changed, predicting a release/bump when one happened, anticipating commit kinds) — so I
   optimize real maintainer foresight, not keyword stuffing.
3. **As a reviewer**, any change to `score.py` is checked against this written contract at the
   SDD phase boundary — so the anchor's meaning doesn't drift.

## Acceptance criteria (EARS)

### Ground truth, not similarity

- The anchor SHALL grade a plan against *structural ground truth* derived from the revealed
  window (which top-level modules changed, whether a release happened, its bump level, commit
  kinds, addressed backlog issues) — NOT against free-text similarity.
- The lexical `trajectory_overlap` SHALL remain a diagnostic only and SHALL NOT feed the score.

### Module recall

- `module_recall` SHALL be the fraction of actually-changed top-level modules the plan named
  (by significant-token overlap of the plan's `title`/`theme`), in `[0, 1]`.
- WHEN file-weighted recall (`weighted_module_recall`) is present THE scalar anchor SHALL prefer
  it over plain `module_recall`, so credit reflects where change actually concentrated.

### Release & bump

- `release_signaled` SHALL be true only for a *genuine* release subject in the window (explicit
  release wording or a version-leading subject) — an incidental version mention SHALL NOT count.
- `release_match` SHALL be `release_signaled == release_predicted`.
- WHEN a release was signaled THE release-prediction correctness SHALL count toward the scalar;
  WHEN no release was signaled it SHALL NOT (so "predicted nothing" isn't trivially rewarded).
- `bump_actual` SHALL be the semver delta between `base_version` (version at freeze T) and the
  revealed release version, or `None` when no release/base is known; `bump_match` SHALL compare
  it to the agent's normalized `version_bump`, and count toward the scalar only WHEN
  `bump_actual is not None`.

### Commit-kind & backlog

- `kind_recall` SHALL be the fraction of revealed commit kinds (conventional-commit / release
  subjects) the plan's item kinds anticipated.
- `backlog_recall` SHALL be reported as an inspectable diagnostic of addressed-issue
  anticipation, but SHALL NOT feed the scalar `objective_component` (ranking-relevant fields
  only — #148).

### Composition & determinism

- `objective_component(objective)` SHALL collapse the ranking-relevant fields into a single
  value in `[0, 1]`.
- `composite_score(winner, objective, w_judge, w_objective)` SHALL blend the pairwise-judge
  outcome (`A`=1.0 / `tie`=0.5 / `B`=0.0) with `objective_component` at normalized weights
  (default `0.6` judge / `0.4` objective).
- All of the above SHALL be deterministic and reproducible offline (`VANGUARSTEW_OFFLINE=1`),
  with no network.

### Robustness (per constitution)

- IF a plan or revealed field is malformed (a non-string title/theme/kind, a non-list
  `plan`/`revealed`/`open_issues`/`releases`) THEN scoring SHALL coerce/guard and continue —
  per `AGENTS.md` → *Benchmark integrity* — so one bad field never aborts a replay run.

## Out of scope

- The **pairwise judge** — its prompt, model, dual-order handling, and winner parsing (its own
  spec). This spec only fixes how the judge outcome *blends* with the anchor.
- **Task generation**, **freeze**, and **leakage** — the revealed window is an input here;
  producing it leaklessly is specified elsewhere.
- The exact *weights/tuning* values (they are declared parameters, revisitable at registration).

## Verification

Already exercised deterministically offline by `tests/test_score.py` (module/release/bump/kind
recall, release-subject discrimination) and `tests/test_compose.py`
(`objective_component`/`composite_score` blending, and that backlog stays out of the scalar).
This spec adds no code and does not require new tests.
