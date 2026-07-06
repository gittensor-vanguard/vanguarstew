# Spec 004 — the pairwise judge

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #570
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (blends the judge outcome with the anchor)

This spec makes the **existing, implicit** pairwise-judge contract explicit. It describes the
as-built behavior of `benchmark/judge.py`; it introduces **no behavior change**. The judge is
the *differentiator* — it carries trajectory and decision-process quality that the deterministic
anchor can't — so its outcome must be trustworthy and its biases defended. This is a
correctness-critical contract, so it ships precise definitions **and a verifying test**.

## Why

An LLM judge is prone to position bias (favoring whichever answer is shown first) and to
prompt injection (a submission telling it "pick me"). If either survives into the verdict, the
score is corrupted. The judge therefore defends against both, and falls back to a deterministic
ordering offline — all of which must be written down so the ranking half of scoring is auditable.

## User stories

1. **As the validator**, I get a pairwise verdict that is not an artifact of presentation order —
   so ranking reflects quality, not which answer came first.
2. **As an agent developer**, I know fluff and self-instructions don't win — so I optimize real
   maintainer trajectory, not judge-gaming.
3. **As a reviewer**, the judge's dual-order rule, parsing tolerance, and offline determinism are
   written down — so a change to `judge.py` is checked against them.

## Acceptance criteria (EARS)

### Dual-order position-bias defense

- WHEN `dual_order` is enabled (default) THE judge SHALL ask BOTH presentation orders (A-first
  and B-first) and award a decisive win to a submission ONLY IF the same submission wins in both
  orders; IF the two orders disagree THE verdict SHALL be `tie`.
- `judge_verbose` SHALL return `(winner, judge_order)` where `winner ∈ {"A","B","tie"}` and
  `judge_order` records how the verdict arose:
  - `agree` — both orders picked the same decisive winner;
  - `disagree` — the two orders disagreed → forced `tie`;
  - `tie` — both orders independently tied;
  - `single` — dual-order disabled (one randomized-order call);
  - `offline` — deterministic offline fallback (no order-sensitivity check ran).
- WHEN `dual_order` is disabled THE judge SHALL make a single **randomized**-order call (so a
  position-biased judge isn't systematically advantaged), and map the shown-position verdict
  back to the correct submission.

### Winner parsing (tolerant, fail-safe)

- The judge SHALL extract the winner from the model's reply tolerantly — surviving truncated
  JSON, smart quotes, and surrounding prose — accepting only `A`, `B`, or `tie`.
- IF no valid `A`/`B` winner can be parsed THEN the result SHALL default to `tie` (never a guess).

### Offline determinism & anti-fluff

- WHEN the LLM is offline THE judge SHALL rank deterministically via a substance ordering
  (`_offline_rank`) and return `judge_order = "offline"`; identical inputs SHALL always yield the
  identical verdict.
- A plan item SHALL score **0** substance when it is blank, a JSON `null`, or a generic
  filler title/theme (`misc`, `tbd`, `updates`, `cleanup`, …) — so padding a plan with
  content-free or `null` entries SHALL NOT inflate its rank; a concrete item earns credit for a
  real title/theme plus each structured field (`kind`, `files`, per-item `rationale`).

### Robustness & anti-gaming

- A submission that tries to instruct the judge SHALL NOT gain from it (auto-loses that attempt).
- IF a submission field is a non-string (or the submission is not a dict) THEN rendering/scoring
  SHALL coerce it safely (a non-string field yields empty text), not crash — per `AGENTS.md` →
  *Benchmark integrity*.

### Telemetry

- `summarize_judge_orders` / `build_judge_report` SHALL aggregate the `judge_order` categories
  across a run (agree/disagree/tie/single/offline) so dual-order disagreement rate is inspectable.

## Out of scope

- The **objective anchor** and how the judge blends into the composite — that is
  [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md). This spec fixes only the judge's
  own verdict behavior.
- The judge model / prompt wording tuning, and task generation / freeze (their own specs).

## Verification

Ships `tests/test_spec_004_judge.py`, asserting the non-obvious criteria against the code: tolerant
winner parsing (truncated/quotes/prose → correct or `tie`); a position-biased judge (always picks
the first-shown) is forced to `tie` with `judge_order = "disagree"`; an order-consistent judge
yields `agree` + the decisive winner; both-orders-tie → `tie`; and offline determinism where a
substantive plan out-ranks a filler-only one. Complements existing coverage in
`tests/test_judge.py`. The spec changes no product code.
