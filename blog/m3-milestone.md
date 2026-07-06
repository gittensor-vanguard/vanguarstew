# vanguarstew completes M3 — generalization in under one week

*July 7, 2026*

We just closed the M3 milestone: a **general maintainer agent that scores on repos it has
never been tuned against**. The acceptance run completed with **zero crashes** and a
`generalization_gap` of **0.097** — held-out performance did not collapse. M3 is done.

What makes this worth talking about isn't just the result. It's the pace.

## From zero to M3 in six days

vanguarstew's first commit landed **July 1, 2026**. Six days later, we have:

- **362 merged pull requests** from 48 unique contributors
- M0 (agent contract) → M1 (replay harness) → M2 (scoring + leakage) → M3 (generalization)
- A 5-repo curated benchmark set with held-out partitioning
- A generalization report with pairwise judge robustness
- A project constitution (`AGENTS.md`) in EARS notation
- A spec-driven development methodology
- A test-branch CI workflow that auto-closes mis-targeted PRs

Every milestone had a concrete acceptance test. Every one passed.

## What landed in M3

| Deliverable | What it is |
|---|---|
| Curated repo set | 5 repos (hatch, pluggy, feedparser, httpx, hpack) — 3 tuned, 2 held-out |
| `--generalization` | Single-command tuned + held-out replay with `generalization_gap` report |
| Judge robustness | Pairwise disagreement tracking, evidence anchoring, dual-order judging |
| Composite scoring | Objective anchor (module recall, kind recall, backlog recall, release match) + judged layer |
| Dimension weighting | `--w-judge` / `--w-objective` knobs for tuning the composite |
| Leakage hardening | Forward-reference stripping, tag-creation-date filtering, frozen context auditing |
| Agent hardening | Non-string field coercion across philosophy, planner, decider, reviewer, and judge |

## The acceptance run

```json
{
  "generalization_gap": 0.097,
  "partitions": [
    {"selection": "tuned",    "repos": ["hatch", "pluggy", "feedparser"]},
    {"selection": "held_out", "repos": ["httpx", "hpack"]}
  ],
  "crashes": 0
}
```

![M3 acceptance run demo](../docs/vanguarstew-m3.gif)

The gap is small and positive — the agent transfers to unseen repos without
collapsing. That's the signal M3 was designed to produce.

## Why this is a big milestone

Generalization is the line between a repo-specific tool and a general maintainer.
If the agent only works on repos it was tuned on, it's a script. If it works on
repos it has never seen, it's a system.

M3 crossed that line. With a held-out partition that was never in the training
loop, the agent still produces decisions the judge prefers over the heuristic
baseline. The composite score holds. The objective anchor tracks.

For SN74 (the gittensor repo-maintainer subnet), this is the foundation.
Miners will submit agents that are scored against our benchmark — and the
benchmark must be defensible: no memorization, no leakage, no gaming. M3
is the answer to those three problems.

## What's next — M4 hardening, then M5 subnet launch

M4 closes the remaining crash-and-correctness gaps so the benchmark runs clean
on any reasonable input. M5 registers the repo on gittensor and wires the full
submit → evaluate → rank loop.

---

*Roadmap: [ROADMAP.md](/ROADMAP.md)*
*Constitution: [AGENTS.md](/AGENTS.md)*
*M3 acceptance run: [m3_acceptance_result.json](/m3_acceptance_result.json)*
