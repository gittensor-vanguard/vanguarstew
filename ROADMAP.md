# Roadmap & Milestones — vanguarstew (SN74 repo-maintainer agent)

Goal: a general repository-maintainer agent, optimized against a benchmark derived from real GitHub history, mature enough to run fully agentic on gittensor (the way SN66 "ninja" runs for coding). Each milestone has a concrete **deliverable** and an **acceptance test** — done means the acceptance test passes, not "looks done."

---

## M0 — Scaffold & agent contract

The agent runs and returns a well-formed maintainer decision.

- Repo scaffold, packaging, manifest (`vanguarstew_agent_files.json`).
- Base agent with the fixed `solve(repo_path, request, ...)` entrypoint.
- Agent workflow wired: **infer philosophy → read situation → plan/decide → implement-if-needed**.
- OpenAI-compatible LLM client honoring the managed-inference contract (`api_base`/`api_key`/`model`), plus an offline stub for deterministic dry-runs.
- **Acceptance:** `VANGUARSTEW_OFFLINE=1 python -m pytest -q` passes; `solve()` on a frozen repo returns a decision with `philosophy`, `plan`, `action`, `rationale`.

## M1 — Time-travel replay harness

The core loop runs end-to-end on real history.

- `freeze.py`: check out a repo at commit T and build the **knowable-at-T** context, stripping forward-looking signal.
- `taskgen.py`: generate replay tasks from a repo's git history (freeze point + revealed next-N).
- `judge.py`: **pairwise** LLM judge (challenger plan vs. current-best plan, given the revealed trajectory).
- `runner.py`: orchestrate freeze → run agents → judge → tally **decisive wins**.
- **Acceptance:** end-to-end replay on 1–2 *leakage-safe* repos produces a pairwise win/loss record between two agents; re-runs are stable.

## M2 — Scoring dimensions & leakage hardening

The score is defensible, not just subjective prose-judging.

- **Objective anchor:** deterministic scoring of concrete decisions (merge/reject, labels, reviewer, version bump) vs. actual.
- **Judged layer:** trajectory/direction + decision-process rubrics, pairwise; rubric anchoring against fluff.
- **Leakage defenses:** offline sandbox; forward-signal stripping; **repo/time-point selection past model training cutoff**; obscure/private-repo support.
- Richer context via GitHub API (issues, PRs, reviews, releases) where available.
- **Acceptance:** composite score = objective anchor + judged layer; documented leakage controls; an agent that merely restates a memorized outcome does **not** win.

## M3 — Generalization

A *general* maintainer, not one tuned to a single repo.

- Diverse + **held-out** repos; dimension-weight tuning; judge-robustness checks.
- Spot-check / manual review of the top agent (as ninja does).
- **Acceptance:** scores track maintainer skill on repos the agent was never tuned against; held-out performance doesn't collapse.

## M4 — gittensor integration / tau reuse

Fully agentic, 66-style.

- Decide reuse vs. fork of `tau` (Generate → Solve → Compare/eval) and its managed inference.
- Register the repo on gittensor; wire the full submit → evaluate → rank loop (subnet economics handled by gittensor).
- **Acceptance:** miners can submit a maintainer agent and have it evaluated and ranked autonomously, end-to-end.
