# Architecture & repository topology

This note records how the project is organized today and how it is expected to grow, so the
repo structure stays deliberate rather than accidental.

## Today: one repo, two halves

Everything lives in `vanguarstew`, split in-code by ownership:

- **`agent/` + `agent.py` — the miner-editable agent.** The `solve()` entrypoint and the
  philosophy → plan → decide → implement steps. This is what a miner forks, edits, and submits.
- **`benchmark/` — the validator-owned harness.** Freeze a repo at a point in time, generate
  replay tasks from history, run agents, and judge them pairwise. Changes here affect how
  everyone is scored.

Keeping both in one repo is intentional while the design is still moving.

## Layout

```
agent/                 the maintainer agent (the part a contributor/miner edits)
  llm.py               OpenAI-compatible client (managed-inference contract)
  context.py           loads the frozen, knowable-at-T repo state
  philosophy.py        step 1: infer the repo's maintainer philosophy
  planner.py           step 3a: plan the next N actions / PRs
  decider.py           step 3b: concrete decisions (merge/triage/release/patch)
agent.py               the fixed entrypoint: solve(repo_path, request, ...)
benchmark/             the evaluation harness (validator-owned; miners don't edit)
  freeze.py            freeze a repo at commit T, build leakage-safe context
  taskgen.py           generate replay tasks from GitHub history
  judge.py             pairwise judge over philosophy + plan + reasoning
  score.py             objective scoring anchor (module recall + release match)
  runner.py            orchestrate the replay eval, tally decisive wins
scripts/run_eval.py    CLI to run an end-to-end replay
vanguarstew_agent_files.json   manifest of miner-editable files (mirrors tau)
```

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
    "version_bump": "major|minor|patch|null",  # predicted next release bump (scored)
    "patch": "<unified diff>|null",
    "rationale": "...",                # the reasoning the judge evaluates
    "logs": "...", "steps": 0, "cost": None, "success": True,
}
```

`version_bump` is an accepted challenger output and feeds the objective anchor: when the
revealed window cuts a release, `benchmark/score.py` derives `bump_actual` from the semver
delta between the last two versions seen in the revealed commit subjects, and reports
`bump_match` (whether the agent's `version_bump` matched). Windows with fewer than two
versions leave `bump_actual` null, so a no-release run isn't scored on a trivial match.

## Planned split (around M2)

Once the miner/validator boundary stabilizes, split into two repos, mirroring how SN66
separates its miner harness from its validator:

- **`vanguarstew`** — the miner agent harness only (fork / edit / submit). Small and stable.
- **`vanguarstew-validator`** — task generation, freeze, judge, scoring, runner, and
  deployment. Validator-owned; miners never edit it.

The split is about clean ownership, independent versioning/deploy of the validator, and
matching the ecosystem's mental model — not secrecy.

## Benchmark data

The curated, leakage-safe task sets — vetted repos and commit windows (recent / obscure,
per the leakage constraints), frozen snapshots, and revealed-history references — will live
as a separate benchmark dataset (its own repo or a hosted dataset) once M2 produces real
tasks. This is the most reusable asset the project produces.

## Leakage defenses

Because the reference is public GitHub history, the benchmark actively resists leakage:

- **No internet in the sandbox** beyond the managed inference proxy.
- **Knowable-at-T only** — the frozen context is built from commits/issues/PRs/releases that
  existed at T; nothing created (or a release published) after T is included.
- **Forward-reference scrubbing** (`benchmark/leakage.py`) — even within knowable-at-T text,
  issue/PR back-references (`#N`), GitHub issue/PR/commit links, and raw SHAs are masked, so a
  commit subject or README can't cross-reference the future.
- **Recent-window + rotation** freeze-point selection (`benchmark/taskgen.py`) — prefer recent
  points (past a model's training cutoff) and rotate deterministically so answers aren't reused.
- **Repo diversity / held-out repos** (M3) — generalization is scored on unseen repos.

## Principle

Create a new repo only when it has real content to hold. Keep boundaries in-code until they
stabilize, then promote them to separate repos.
