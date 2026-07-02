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
