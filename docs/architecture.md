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
tools/                 dev & maintenance tooling — NOT part of the scored agent
  codex_llm.py         optional local `codex`/OAuth LLM backend (dev only; never scored)
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
    "patch": "<unified diff>|null",
    "rationale": "...",                # the reasoning the judge evaluates
    "logs": "...", "steps": 0, "cost": None, "success": True,
}
```

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

### Repo-set config + loader

The list of repositories the benchmark replays is a **checked-in JSON config**, not a
hardcoded array — so the curated, leakage-safe selection is reviewable and versioned. The
shipped `benchmark/repo_sets/example.json` is a **starter/example** whose sources are
placeholders (`OWNER/...`) — copy it and swap in vetted repos for a real run. `benchmark/
repo_set.py` loads and **strictly validates** any config, at both the **top level** (only
`name` / `description` / `strategy` / `repos` allowed; metadata must be strings; a stray or
misspelled key is rejected) and per entry — since a leakage-safe set is only as trustworthy
as its config.

Each entry carries:

- `name` — unique id; `source` — git URL or local path.
- `tier` — `recent` or `obscure`, the two leakage-resistance strategies (past-cutoff recency
  vs. low-traffic obscurity).
- `held_out` — reserve the repo for generalization scoring (see the held-out eval above).
- `freeze_window` — hints that map onto `run_replay`'s knobs: `recent_bias`, `rotation_seed`,
  and `after` / `before` / `min_history` bounds for freeze-point selection.

The loader returns a typed `RepoSet` with `tuned()` / `held_out()` / `by_tier()` /
`sources()` views, so the runner consumes a validated selection instead of ad-hoc paths:

`load_repo_set(path)` takes a **required** path — there is no implicit default, so a config
is always chosen deliberately (never the placeholder starter by accident). Use the exported
`EXAMPLE_REPO_SET` to load the shipped example explicitly.

```python
from benchmark.repo_set import EXAMPLE_REPO_SET, load_repo_set
rs = load_repo_set("path/to/curated.json")   # or load_repo_set(EXAMPLE_REPO_SET) for the starter
tuned   = [e.source for e in rs.tuned()]
heldout = [e.source for e in rs.held_out()]
```

## Leakage defenses

Because the reference is public GitHub history, the benchmark actively resists leakage:

- **No internet in the sandbox** beyond the managed inference proxy.
- **Knowable-at-T only** — the frozen context is built from commits/issues/PRs/releases that
  existed at T; nothing created (or a release published) after T is included.
- **As-of-T reconstruction of mutable fields** (`benchmark/github_context.py`) — some GitHub
  fields the live REST snapshot exposes are mutable and would otherwise leak present-day state:
  - *Milestone state* is derived from `created_at`/`closed_at` (`_milestone_at`) — `"closed"`
    only when it was already closed by T.
  - *Issue/PR label membership* is reconstructed by replaying the item's timeline
    `labeled`/`unlabeled` events up to T (`_labels_at`); when the timeline can't be read
    (offline, rate-limited, or no label events), labels are **omitted** (`labels_as_of_t:
    false`) rather than copied live — fail-closed, never leak.
  - *Intentionally omitted* (not reconstructable from a cheap as-of-T source): the repo-wide
    label catalog and milestone `due_on` are dropped from the enriched context rather than
    copied live. Issue/PR titles are still the live values, so consumers must not treat them
    as historically exact; timeline-based reconstruction can be extended to more fields later.
- **Forward-reference scrubbing** (`benchmark/leakage.py`) — even within knowable-at-T text,
  issue/PR back-references (`#N`), GitHub issue/PR/commit links, and raw SHAs are masked, so a
  commit subject or README can't cross-reference the future.
- **Recent-window + rotation** freeze-point selection (`benchmark/taskgen.py`) — prefer recent
  points (past a model's training cutoff) and rotate deterministically so answers aren't reused.
- **Repo diversity / held-out repos** (M3) — generalization is scored on unseen repos.

### Forward-reference scrubbing policy

`strip_forward_refs()` (`benchmark/leakage.py`) neutralizes future-pointing references in the
free-text fields of the frozen context (commit subjects, issue/PR titles, README excerpt,
release/milestone names). It masks exactly three things:

- **Issue/PR back-references** — `#123` → `#ref`.
- **GitHub deep links** — `https://github.com/owner/repo/{issues,pull,commit,compare}/…` → `<link>`.
- **Raw commit SHAs** — a 7–40 char hex token → `<sha>`, **but only when it contains a hex
  letter (`a`–`f`)**.

**Why bare numeric tokens are preserved:** a SHA's alphabet `[0-9a-f]` is a superset of the
digits, so an all-numeric token (a count, a percentage, a year like `2024`, a version part) is
indistinguishable from a short hex SHA by shape alone. Masking those would corrupt legitimate
numeric content the agent needs, so `_looks_like_sha()` requires at least one `a`–`f` letter
before a token is treated as a SHA. The trade-off is deliberate: an all-numeric SHA-shaped
token is left intact rather than risk shredding real numbers — masking is scoped to tokens that
are *unambiguously* hex.

This policy is pinned by regression tests in `tests/test_leakage.py`:
`test_strip_forward_refs_masks_refs_links_and_shas`,
`test_strip_forward_refs_preserves_plain_numbers`, and
`test_strip_forward_refs_still_masks_hex_shas_among_plain_numbers` (hex SHAs are still masked
even when surrounded by plain numbers). Changes to the masking behavior should update these
tests and this note together.

## Principle

Create a new repo only when it has real content to hold. Keep boundaries in-code until they
stabilize, then promote them to separate repos.
