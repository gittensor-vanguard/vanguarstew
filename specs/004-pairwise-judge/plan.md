# Plan 004 — pairwise judge

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #570

How the [spec](./spec.md) maps onto `benchmark/judge.py` as-built. No new product code; this
records the contract surface + control flow so future judge changes are reviewed against a plan.

## Architecture / control flow

```
pairwise_judge(...)              # thin wrapper → just the winner
  └─ judge_verbose(context, a, b, revealed, llm, rng, dual_order=True) → (winner, judge_order)
       ├─ IF llm.offline:  winner = compare _offline_rank(a) vs _offline_rank(b); order="offline"
       ├─ IF dual_order:                                             # position-bias defense
       │    v_ab = _judge_order(ctx, a, b, …)  → w_ab
       │    v_ba = _judge_order(ctx, b, a, …)  → w_ba
       │    w_ab==w_ba∈{A,B} → (w_ab,"agree") ; both tie → ("tie","tie") ; else → ("tie","disagree")
       └─ ELSE:            single randomized-order call → map back to A/B ; order="single"
_judge_order(...)                # one fixed-order judgment
  └─ llm.chat(SYSTEM, user=render(first)+render(second)+question) → _parse_winner → first/second/tie
_parse_winner(text)              # tolerant regex → "A"/"B"/"tie" (default "tie")
_offline_rank(submission)        # deterministic: _plan_substance + reasoning length
_item_substance / _plan_substance# anti-fluff: filler/blank/null items score 0
summarize_judge_orders / build_judge_report   # aggregate judge_order telemetry
```

## Data model

### Inputs

`context` (frozen, knowable-at-T), two `submission` dicts (each `philosophy`/`plan`/`rationale`,
per `specs/001`), `revealed` window, `llm`, optional `rng` (seeded), `dual_order` flag.

### Output of `judge_verbose`

| Field | Values | Meaning |
| ----- | ------ | ------- |
| `winner` | `A` / `B` / `tie` | challenger-perspective decisive verdict |
| `judge_order` | `agree` / `disagree` / `tie` / `single` / `offline` | how the verdict arose (telemetry) |

### Substance rule (anti-fluff)

| Plan item | Substance |
| --------- | --------- |
| real title/theme | 1 + 1 per structured field (`kind`, `files`, per-item `rationale`) |
| blank / `null` / filler title (`misc`,`tbd`,`updates`,…) | 0 |

## The invariants this pins

- **Order symmetry:** a decisive win requires agreement across the swap; disagreement ⇒ `tie`.
- **Parse safety:** unparseable/ambiguous ⇒ `tie`, never a guessed winner.
- **Offline determinism:** same inputs ⇒ same verdict, `judge_order = "offline"`.
- **Anti-fluff/anti-gaming:** filler/null padding scores 0; self-instructions don't win.

## Verification strategy

`tests/test_spec_004_judge.py` (this PR) exercises each invariant with scripted fake judges;
broader behavior is in `tests/test_judge.py`. A future task MAY add property tests over the
dual-order truth table.

## Out of scope for this plan

Changing any judge behavior, the objective anchor, or the composite blend. Code changes follow
the SDD loop in their own specs/PRs.
