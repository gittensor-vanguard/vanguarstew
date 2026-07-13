# What vanguarstew is really building: a measurable AI maintainer

*July 13, 2026*

Most AI-agent projects are a variation on the same pitch: a framework for wiring up
LLM calls, or an agent that resolves a GitHub issue. Both are crowded spaces. vanguarstew
is doing something different, and it's worth saying plainly what the end goal is.

**vanguarstew is becoming the first measurable, public, self-improving AI software
maintainer.**

Three things, each individually rare, that together nobody else has:

1. **It co-maintains a real repository, in the open** — reviewing real pull requests as a
   supervised co-maintainer, not in a demo sandbox.
2. **Every improvement to it is scored by a benchmark that predicts what real maintainers
   actually did** — by replaying real git history: freeze a repo at a past commit, ask the
   agent what the maintainers should do next, then check its answer against what they
   genuinely did. Scored on public *and* held-out repositories, with a Pareto floor that
   blocks any change that games one axis at the expense of another.
3. **Its maintainer skill is tracked on a public leaderboard** — you can watch it improve.

## Why not "the best agent framework"

Because that's the wrong category. LangGraph, AutoGen, CrewAI, the OpenAI Agents SDK, the
new Microsoft Agent Framework — these are excellent *orchestration* tools. Comparing
vanguarstew to them is like comparing an inference engine to a deep-learning framework: a
category error. vanguarstew isn't plumbing for building agents. It's a specialist at one
hard, specific task — **maintainer judgment**: knowing what a codebase wants next, what to
merge, what to triage, when to cut a release.

Nobody has a popular benchmark for *that*, because measuring maintainer judgment is genuinely
new. Issue-resolution benchmarks like SWE-bench measure whether a model can write a patch
that passes hidden tests — a real and valuable thing, but a different one. Predicting the
*direction* a senior maintainer will take a project is a separate skill, and it's the one
vanguarstew is built to measure and optimize.

## The proof we're building toward

The goal isn't a number you have to trust us on. It's a **verifiable demonstration**:

> Freeze a repository people recognize at a past commit. Before revealing what came next,
> the agent predicts the maintainers' next actions. Then show it called them right — the
> release, the module, the refactor — against the actual git history anyone can pull up on
> GitHub themselves.

That's the whole point of building on real history: the receipt is public and independently
checkable. You don't have to believe our benchmark; you can verify the prediction yourself.

## The flywheel

This is why the contribution-scoring mechanism matters so much. It isn't bureaucracy — it's
the engine:

- Contributors improve the agent's **real predictive accuracy** — how often it names the
  modules, kinds of work, and releases that maintainers actually produced next, on repos it
  has never seen.
- The benchmark scores each change, anti-gamed and on held-out targets, so only genuine
  improvement counts.
- The leaderboard shows verifiable maintainer-foresight climbing over time.
- That climbing record, plus the frozen-repo demonstration, is the proof — which draws more
  contributors, who push the accuracy higher.

Every merged improvement makes the agent measurably better at anticipating real maintainers,
and that improvement is public and checkable. That's the loop.

## What's next

Two milestones make this concrete (see the [roadmap](../ROADMAP.md)):

- **M7 — a legible foresight metric:** turn the internal composite score into a single,
  objective accuracy figure an outsider instantly understands and can verify against real
  history, and make it the leaderboard's headline.
- **M8 — the verifiable demonstration:** a clean, fair, reproducible frozen-repo prediction
  on a well-known repository — freeze commit, model, and cutoff stated up front — plus the
  public record of the metric climbing over a real track of merged, genuinely-improving PRs.

We're not trying to win an argument about which agent framework is best. We're trying to
prove, in public and in a way anyone can check, that an AI can learn to maintain software
like a senior maintainer — and to get measurably better at it every week.
