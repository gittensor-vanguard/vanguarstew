# Roadmap & Milestones — vanguarstew (SN74 repo-maintainer agent)

Goal: a general repository-maintainer agent, optimized against a benchmark derived from real GitHub history, mature enough to run fully agentic on gittensor (the way SN66 "ninja" runs for coding). Each milestone has a concrete **deliverable** and an **acceptance test** — done means the acceptance test passes, not "looks done."

---

## North Star

**vanguarstew is becoming the first measurable, public, self-improving AI software maintainer.**

Three things that are each individually rare, and together nobody else has:

1. **It co-maintains a real repository, transparently** — reviewing real PRs in the open as a supervised co-maintainer.
2. **Every improvement to it is scored by a rigorous, anti-gaming benchmark that predicts what real maintainers actually did** — time-travel replay on real git history, public + held-out repo targets, and a Pareto floor that blocks any PR that trades one axis off against another.
3. **Its maintainer skill is tracked climbing on a public leaderboard over time.**

This is deliberately **not** "another agent framework" (orchestration plumbing is a crowded, vendor-owned space) and **not** "another issue-resolution benchmark." It is a category nobody else occupies: an AI whose *judgment as a maintainer* — what to plan, triage, review, release — is measured, verifiable, and provably improving in public.

The proof we are building toward is a **verifiable demonstration**, not a number you have to take on trust: freeze a well-known repository at a past commit, have the agent predict the maintainers' next actions, and show it called them right against the *actual* git history anyone can check on GitHub. Same principle as a reproducible benchmark receipt — the evidence is public and independently checkable. Milestones M7–M8 below are the concrete path to that demonstration.

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
- [x] Merge-block + top band: a measured regression is a hard merge block for `agent/` PRs, not
  just a label cap; a large, clean win on every axis (≥5× the noise floor, both components
  improving) earns the top band, `perf:xl` (×4.0). #1302
- [x] `REVIEW.md` "Evidence requirement for `agent/` PRs": documents the full band ladder
  (`perf:xs`–`perf:xl`, and the `blocked` regression case) and what each requires.
- [x] Public CI smoke check (`agent-benchmark-smoke.yml`): crash/output-shape check on
  every `agent/`-touching PR, offline-safe (no secrets, safe on fork PRs) — explicitly
  documented as *not* the scoring evidence itself.
- **Status:** ✅ complete. `score_pr_delta.py` verified against the Goodhart-trap case
  (composite rises only because one axis was sacrificed for the other → correctly
  rejected) and against real `run_eval` artifacts, not just synthetic test dicts. Full
  suite green (3675 passed).

## M6 — gittensor integration ✅

Live on gittensor as a scored repository — no separate subnet fork needed.

- [x] **Reuse vs. fork of `tau`:** resolved to **reuse**. Rather than standing up a separate 66-style Generate → Solve → Compare subnet with its own managed inference, vanguarstew registered as a repository on the existing gittensor repo-scoring subnet, which already runs the submit → evaluate → rank loop over real pull requests. No parallel eval/inference infrastructure to maintain.
- [x] **Registered on gittensor** — live in the subnet's `master_repositories.json`: `maintainer_cut` 0.5, `trusted_label_pipeline` true, the full `perf:xs`–`perf:xl` multiplier ladder (0.5 → 4.0) plus `mult:contribution`, eligibility gates (`min_credibility` 0.5, `max_open_pr_threshold` 2), a 7-day PR scoring window with 3-day sigmoid time-decay, and `test` registered as an additional accepted branch.
- [x] **Submit → evaluate → rank loop live:** contributors open PRs against the agent; gittensor's own validators score and rank the repository's contributions autonomously through the trusted label pipeline; subnet economics are handled by gittensor. The `perf:*` bands the benchmark measures map directly to the on-chain `label_multipliers`.
- [x] **Acceptance:** vanguarstew is a live, earning repository on gittensor, carrying a real emission share (~0.099 in the subnet's repository config) and scored end-to-end by the subnet's validators with no manual intervention in the ranking loop.
- **Status:** ✅ complete. Registered and earning on gittensor via the trusted label pipeline; the measured `perf:*` ladder submitted by the benchmark maps 1:1 to on-chain label multipliers.

## M7 — Legible, verifiable maintainer-foresight metric

Turn the internal composite score into a single number an outsider instantly understands and can check — the leaderboard's hero stat.

- A public **maintainer-foresight accuracy** metric built from the *objective, verifiable* side of the score: did the agent predict the modules, commit-kinds, and releases that the maintainers actually produced next. This is the half that anyone can independently confirm against real git history — no trust in our judge required.
- Raise objective predictive accuracy as the primary optimization target contributors compete on (the benchmark already rewards exactly this): every `agent/` PR is measured on whether it makes the agent predict *what real maintainers did* more accurately, on repos it has never seen.
- Surface the metric as the leaderboard's headline, with the composite/judge detail available underneath for depth.
- **Acceptance:** the leaderboard leads with a single objective foresight-accuracy figure on the held-out target; it moves only when a merged PR genuinely improves verifiable prediction accuracy, and cannot be moved by prose-quality alone.

## M8 — The verifiable public demonstration

The flagship, checkable "here's the receipt" moment.

- A clean, **fair** frozen-repo prediction demonstration on a repository people recognize: state the freeze commit, the model, and the context cutoff up front (so it cannot be dismissed as cherry-picked), have the agent predict the next maintainer actions, then show the match against the real revealed history.
- A public, continuously-updated record: the foresight metric climbing over a real track record of merged, genuinely-improving PRs against a fixed anchor — the "optimization journey," not a one-off.
- **Acceptance:** a third party can independently reproduce the demonstration from the published freeze point and model, and confirm both the individual prediction and the direction of the leaderboard trend against public git history.
