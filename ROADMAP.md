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

## M3 — Generalization ✅

A *general* maintainer, not one tuned to a single repo.

- [x] Diverse + **held-out** repos: `benchmark/repo_sets/curated.json` (5 repos), repo-set config, `--repo-set` wiring.
- [x] Generalization report: `run_eval --generalization` replays tuned+held-out partitions, reports `generalization_gap`.
- [x] Judge-robustness: disagreement tracking, pairwise judging, evidence anchoring.
- [x] Spot-check / manual review of the top agent (as ninja does).
- [x] **Acceptance run:** `run_eval --generalization` on curated set → `generalization_gap = 0.097`, zero crashes. Held-out performance does not collapse.
- **Status:** ✅ complete. Acceptance run passed. See `m3_acceptance_result.json` and `blog/m3-milestone.md`.

## M4 — Hardening & release readiness ✅

Close the crash-and-correctness gap so a full benchmark run completes clean.

- [x] **Agent hardening:** every field the LLM emits is guarded against non-string types. #297, #313, #317 closed.
- [x] **Benchmark scoring:** module-recall farming fixed (#289), backlog threshold reachable for single-word titles (#308), composite-score wiring (#341).
- [x] **Leakage lockout:** tag-creation-date filter for frozen releases (#332), release-tag scrubbing in `scrub_context` (#330), forward-reference masking in git-only fallback (#312).
- [x] **Tooling:** `compare_eval` CLI for diffing replay artifacts (#306), `--fail-under` score floor for CI gating (#318, #367).
- [x] **Acceptance run:** M3 acceptance completed clean with `generalization_gap = 0.097`, zero crashes across 5 repos.
- **Status:** ✅ complete. Benchmark runs clean on 5 repos; no agent crashes from malformed LLM output; leakage audit clean; full test suite green (3659 passed).

## M5 — Measured, anti-gaming contribution scoring ✅

A PR's value label is earned by a measured benchmark delta, not a maintainer's read of the
diff — closing the "label reflects a guess" gap the reward mechanism would otherwise be
vulnerable to.

- [x] `scripts/score_pr_delta.py`: diffs two `run_eval` artifacts (baseline vs. PR's agent,
  same repo-set) and applies a **Pareto floor** — composite score must measurably improve
  AND neither the judge nor the objective component may regress. Trading one axis for the
  other (sounding better to the judge while the objective anchor quietly drops) is
  rejected, not counted as improvement. #1295
- [x] Merge-block + ceiling label: a measured regression is a hard merge block for
  `agent/` PRs, not just a label cap; a large, clean win on every axis (≥5× the noise
  floor, both components improving) earns a new ceiling label, `mult:breakthrough`
  (×3.0), above `mult:core-correctness` (×2.0). #1302
- [x] `REVIEW.md` "Evidence requirement for `agent/` PRs": documents the full tier ladder
  (blocked/neutral/eligible/breakthrough) and what each requires.
- [x] Public CI smoke check (`agent-benchmark-smoke.yml`): crash/output-shape check on
  every `agent/`-touching PR, offline-safe (no secrets, safe on fork PRs) — explicitly
  documented as *not* the scoring evidence itself.
- **Status:** ✅ complete. `score_pr_delta.py` verified against the Goodhart-trap case
  (composite rises only because one axis was sacrificed for the other → correctly
  rejected) and against real `run_eval` artifacts, not just synthetic test dicts. Full
  suite green (3675 passed).

## M6 — gittensor integration / subnet launch

Fully on-chain, 66-style.

- Decide reuse vs. fork of `tau` (Generate → Solve → Compare/eval) and its managed inference.
- Register the repo on gittensor (#1578 config: maintainer_cut 0.5, trusted_label_pipeline, label_multipliers).
- Wire the full submit → evaluate → rank loop (subnet economics handled by gittensor).
- **Acceptance:** miners can submit a maintainer agent and have it evaluated and ranked autonomously, end-to-end.
