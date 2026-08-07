# OpenVang roadmap

## North star

OpenVang is a role-separated agent factory for operating a Bittensor subnet at
the owner-workflow level. Vanguarstew remains its maintainer-intelligence and
benchmark component; it does not become a universal autonomous owner account.

The factory must make useful work verifiable, bounded, recoverable, and safe
before it is allowed to affect an external system.

## Current foundation

- **Maintainer intelligence:** replay-based repository understanding, planning,
  decision support, and a private live-review runtime.
- **Benchmark integrity:** frozen history, objective anchors, pairwise judging,
  generalization checks, and time-safe persistent-memory evaluation.
- **Verifiable execution:** receipt-safe Polaris TEE integrations for supported
  benchmark jobs. These prove execution integrity; they do not provide workload
  confidentiality.
- **Factory control plane:** typed contracts for validator, maintainer, miner
  QA, builder, product, QA, scheduler, and security QA roles; a durable,
  commitment-only scheduler with bounded budgets and worker leases.

## Near-term sequence

### 1. Private factory control plane

- Keep all specialist work role-scoped and private by default.
- Use the encrypted role-private vault for factory-worker memory; use only
  pre-shaped commitments for cross-role coordination, never private review
  records or derived traces.
- Run the scheduler with durable leases, bounded work budgets, and explicit
  failure states.
- Record only local aggregate operational telemetry; no review content or
  memory evidence enters public status.
- **Acceptance:** restart does not duplicate work or reveal a private artifact.

### 2. Non-privileged adapters

- The first local isolated build/QA adapter binds a claimed task, exact external
  approval, and sealed aggregate result to commitments only; exercise it in a
  controlled pilot with a lease covering the approved execution time.
- Define and exercise the read-only subnet-state adapter against a separately
  reviewed source; it accepts only a fixed identity-free projection and keeps
  only its digest in the private scheduler.
- Require each adapter to declare its role, input contract, output class, and
  failure/timeout behavior.
- **Acceptance:** an adapter cannot access a credential, wallet, GitHub write
  API, or another role's private memory.

### 3. One-subnet pilot

- Select one bounded workflow where independent verification reduces cost or
  fraud risk.
- Use a fixed budget, a separate validator/QA check, and receipt-safe evidence.
- Measure latency, cost, failure rate, and operator friction.
- **Acceptance:** an independent verifier can reproduce the permitted result
  without needing raw private operational material.

### 4. Owner-action gateway

- Design a separate gateway for actions that require an owner: publication,
  repository writes, governance, emissions, or on-chain transactions.
- Use external signing, exact approval binding, idempotency, audit retention,
  and containment/rollback rules.
- The factory remains unable to self-approve or store an owner key.
- **Acceptance:** a malformed, stale, duplicate, or unapproved request cannot
  reach the external effect.

## Non-goals until separately approved

- Autonomous wallet/key access, on-chain transactions, emissions changes, or
  governance votes.
- Automatic public communication or publication of private review material.
- Treating a Polaris integrity receipt as proof of workload confidentiality.
- Sharing raw role-private memory, prompts, reviewer reasoning, or source
  evidence across roles or into benchmark/TEE/public artifacts.

See [docs/openvang-agent-factory.md](docs/openvang-agent-factory.md) for the
enforced role policy and [docs/product-runtime-plan.md](docs/product-runtime-plan.md)
for the private maintainer runtime.
