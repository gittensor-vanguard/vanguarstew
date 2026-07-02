# vanguarstew — SN74 repo-maintainer agent

[![CI](https://github.com/gittensor-vanguard/vanguarstew/actions/workflows/ci.yml/badge.svg)](https://github.com/gittensor-vanguard/vanguarstew/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)

`vanguarstew` is an **SN74 repo-maintainer agent** and the **benchmark** that optimizes it, built to live as a repo on gittensor. It borrows the agentic-workflow + history-derived-benchmark approach of SN66 "ninja" (the coding-agent subnet) and retargets it from *"reproduce the code change"* to *"make the maintainer decisions a strong maintainer would have made."*

The core question it answers is not *"did the agent write good code?"* but *"does the agent understand where this repository is going, and would it have steered it the way the real maintainers did?"*

See [ROADMAP.md](ROADMAP.md) for milestones and [docs/architecture.md](docs/architecture.md) for the repository-topology plan.

## Why this matters

Software development is bottlenecked less by writing code than by **maintaining** it —
triaging, reviewing, prioritizing, and steering a codebase over time. That maintainer
capacity is the real ceiling on how much useful software actually ships.

vanguarstew turns that bottleneck into a measurable optimization problem: *can an agent make
the maintainer decisions a strong human maintainer would have made?* By scoring against real
GitHub history, it builds a benchmark for maintainer capability — and a path to scaling it.

## Demo

![vanguarstew replay demo](docs/vanguarstew-demo.gif)

A replay run: freeze a repo at past commits, plan the next maintainer actions, then score
the plan against what actually changed next (`actual_modules` is the ground truth).

## How it works

```
freeze a repo @ time T  ──>  agent infers the repo's "maintainer philosophy",
                             then plans the next N maintainer actions / PRs
                                      │
reveal the actual history T→T+N  ──>  pairwise judge: whose plan is more
                                      consistent with where the repo actually went?
```

The agent is judged on **direction/theme match** (not exact-PR match), with an **objective anchor** (concrete decisions that have a hard ground truth — merge/reject, labels, reviewer, version bump) and a **judged layer** (trajectory + decision process), scored **pairwise** like ninja, averaged over many freeze-points and repos.

## Layout

```
agent/                 the maintainer agent (the part a miner edits)
  llm.py               OpenAI-compatible client (managed-inference contract)
  context.py           loads the frozen, knowable-at-T repo state
  philosophy.py        step 1: infer the repo's maintainer philosophy
  planner.py           step 3a: plan the next N actions / PRs
  decider.py           step 3b: concrete decisions (merge/triage/release/patch)
agent.py               the fixed entrypoint: solve(repo_path, request, ...)
benchmark/             the evaluation harness (validator-owned; miners don't edit)
  freeze.py            freeze a repo at commit T, build leakage-safe context
  taskgen.py           generate replay tasks from GitHub history
  judge.py             pairwise LLM judge (challenger vs current-best)
  score.py             objective scoring of concrete decisions
  runner.py            orchestrate the replay eval, tally decisive wins
scripts/run_eval.py    CLI to run an end-to-end replay
vanguarstew_agent_files.json   manifest of miner-editable files (mirrors tau)
```

## Quickstart

```bash
# offline dry-run: no network, deterministic stub LLM — proves the loop wiring
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval --repo /path/to/some/git/repo --tasks 2 --horizon 5

# live run against a managed-inference endpoint (ninja-style contract)
python -m scripts.run_eval --repo /path/to/repo --tasks 5 --horizon 5 \
    --model <validator-model> --api-base http://validator-proxy/v1 --api-key "$TOKEN"

# smoke test (no network, no git needed)
VANGUARSTEW_OFFLINE=1 python -m pytest -q
```

## Status

MVP scaffold — Milestone **M0** (see [ROADMAP.md](ROADMAP.md)). The loop runs end-to-end in offline mode; live LLM judging, richer GitHub context (issues/PRs via API), and leakage hardening land in M1–M2.

## Agent contract

The harness invokes the agent with a fixed signature (generalized from ninja's `solve`):

```python
solve(
    repo_path="/tmp/task_repo",        # frozen repo state at time T (+ .vanguarstew_context.json)
    request="plan next 5 actions",     # the maintainer decision being asked for
    model="validator-managed-model",
    api_base="http://validator-proxy/v1",
    api_key="per-run-proxy-token",
) -> {
    "philosophy": {...},               # inferred repo direction / values
    "plan": [...],                     # next maintainer actions / PRs
    "action": "merge|...|plan|patch",
    "patch": "<unified diff>|null",
    "rationale": "...",                # the reasoning the judge evaluates
    "logs": "...", "steps": 0, "cost": None, "success": True,
}
```
