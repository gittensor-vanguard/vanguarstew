# vanguarstew — SN74 repo-maintainer agent

[![CI](https://github.com/gittensor-vanguard/vanguarstew/actions/workflows/ci.yml/badge.svg)](https://github.com/gittensor-vanguard/vanguarstew/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

`vanguarstew` is an **SN74 repo-maintainer agent** and the **benchmark** that optimizes it, built to live as a repo on gittensor. It borrows the agentic-workflow + history-derived-benchmark approach of SN66 "ninja" (the coding-agent subnet) and retargets it from *"reproduce the code change"* to *"make the maintainer decisions a strong maintainer would have made."*

The core question it answers is not *"did the agent write good code?"* but *"does the agent understand where this repository is going, and would it have steered it the way the real maintainers did?"*

See [ROADMAP.md](ROADMAP.md) for milestones and [docs/architecture.md](docs/architecture.md) for the architecture (module layout, agent contract, topology, leakage defenses).

## Why this matters

Software development is bottlenecked less by writing code than by **maintaining** it —
triaging, reviewing, prioritizing, and steering a codebase over time. That maintainer
capacity is the real ceiling on how much useful software actually ships.

vanguarstew turns that bottleneck into a measurable optimization problem: *can an agent make
the maintainer decisions a strong human maintainer would have made?* By scoring against real
GitHub history, it builds a benchmark for maintainer capability — and a path to scaling it.

## Demo

![vanguarstew replay demo](docs/vanguarstew-demo.gif)

A **live** replay against a real model (frozen at a past commit, agent sees only history up
to there). It infers the repo's maintainer philosophy and plans the next actions — its top
call (quick-router fixes) and its read of the direction (toward v1.0) match what the
maintainers actually did next. Scored on trajectory + decision process; the pairwise judge
picks the agent over an empty baseline.

## How it works

```
freeze a repo @ time T  ──>  agent infers the repo's "maintainer philosophy",
                             then plans the next N maintainer actions / PRs
                                      │
reveal the actual history T→T+N  ──>  pairwise judge: whose plan is more
                                      consistent with where the repo actually went?
```

The agent is judged on **direction/theme match** (not exact-PR match), with an **objective anchor** (concrete decisions that have a hard ground truth — merge/reject, labels, reviewer, version bump) and a **judged layer** (trajectory + decision process), scored **pairwise** like ninja, averaged over many freeze-points and repos.

## The agent — what it actually does

The agent is the part contributors improve (it lives in [`agent/`](agent/)). Given a repo
frozen at a moment in time, it decides what a strong maintainer would do next — in four steps:

1. **Infer the "maintainer philosophy."** Before deciding anything, it reads the repo's
   history, README, and recent activity to work out the project's values and direction —
   conservative or fast-moving? refactor-first? heading toward a 1.0 release? This grounds
   everything that follows, and it's the hardest, most important part.
2. **Read the situation.** Open issues, open PRs, recent commits, releases — the maintainer's
   working surface as of that moment (and nothing from the future).
3. **Plan and decide.** Propose the next maintainer actions / PRs and the concrete calls
   (merge / request-changes / reject, triage, reviewer, release) — each with its reasoning.
4. **Implement when needed.** Produce an actual code patch when that's the right move — but
   writing code is only one of the actions a maintainer takes.

The benchmark then scores those decisions against what the maintainers **actually did next**.
So a better agent = better philosophy inference, planning, and judgment — that's what you
improve.

> New here? The module layout and the full agent contract are in
> [docs/architecture.md](docs/architecture.md). The friendliest place to start is a
> [`good first issue`](https://github.com/gittensor-vanguard/vanguarstew/labels/good%20first%20issue).

## Quickstart

```bash
# offline dry-run: no network, deterministic stub LLM — proves the loop wiring
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repo /path/to/some/git/repo --tasks 2 --horizon 5

# live run against a managed-inference endpoint (ninja-style contract)
python -m scripts.run_eval --repo /path/to/repo --tasks 5 --horizon 5 \
    --model <validator-model> --api-base http://validator-proxy/v1 --api-key "$TOKEN"

# multi-repo: replay several repos and aggregate a cross-repo composite (generalization)
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repos /path/to/a /path/to/b --tasks 2 --horizon 5

# smoke test (no network, no git needed)
VANGUARSTEW_OFFLINE=1 python -m pytest -q
```

> **Dev-only backend:** [`tools/codex_llm.py`](tools/codex_llm.py) can drive the benchmark and
> maintenance tooling from a locally-authenticated `codex` CLI (ChatGPT / OAuth, e.g. gpt-5.5)
> with **no API key** — convenient for local exploration. It is for development only: the
> scored `agent.solve` path always uses validator-supplied inference (the managed-inference
> contract in [`agent/llm.py`](agent/llm.py)), never codex.

`--repo` scores one repo; `--repos` scores several and averages each repo's own
`composite_mean` into one cross-repo number. Each single-repo `run_replay` result carries the
composite contract — `composite_mean` plus `composite_parts` (the `judge_mean` and
`objective_mean` it blends, per the `weights`):

```jsonc
// single-repo (--repo) result, composite fields:
{
  "composite_mean": 0.6,                              // mean blended score in [0, 1]
  "composite_parts": { "judge_mean": 1.0, "objective_mean": 0.0 },  // the two blended means
  "weights": { "judge": 0.6, "objective": 0.4 },     // how the parts are blended
  "rows": [ /* per-task: winner, objective, composite */ ]
}
```

The `--repos` aggregate result shape is:

```jsonc
{
  "repos": 2,            // repos given
  "scored_repos": 2,     // repos that produced tasks (and a composite_mean)
  "skipped": 0,          // repos too small for the horizon (kept below, excluded from the mean)
  "composite_mean": 0.6, // mean of each scored repo's composite_mean
  "composite_parts": { "judge_mean": 1.0, "objective_mean": 0.0 },  // means of the per-repo parts
  "per_repo": [ /* each repo's full run_replay result, or its {"error": ...} */ ]
}
```

## Status

**Active development.** The core loop runs end-to-end and is **live-verified against a real
model** (see the demo above). Shipped so far (M0–M2): history-derived replay, an objective
scoring anchor plus a decision-process judge, leakage defenses, and knowable-at-T GitHub
context. Open source (MIT), CI green on Python 3.10–3.12, and registered on gittensor. Next:
generalization across diverse repos (M3) and the fully agentic loop (M4). See
[ROADMAP.md](ROADMAP.md).

## Contributing

Contributions are welcome — the surface is open. Start with [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, and [REVIEW.md](REVIEW.md) for exactly how contributions are gated, reviewed, and
scored (the process is designed to be predictable and reproducible). Browse open
[issues](https://github.com/gittensor-vanguard/vanguarstew/issues) — especially
[`good first issue`](https://github.com/gittensor-vanguard/vanguarstew/labels/good%20first%20issue)
and [`help wanted`](https://github.com/gittensor-vanguard/vanguarstew/labels/help%20wanted).

The module layout and full agent contract live in [docs/architecture.md](docs/architecture.md).
