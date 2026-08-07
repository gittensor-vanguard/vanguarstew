# OpenVang agent factory

## Product direction

OpenVang is building the owner-level operating system for a Bittensor subnet.
It coordinates specialist agents for validator work, maintainer stewardship,
miner QA, building and running, product planning, QA, scheduling, and
defensive adversarial QA. It is not a monolithic autonomous owner account.

The first factory implementation is policy-only: it makes authority, memory,
and publication boundaries machine-checkable before any chain, wallet, or
repository-write adapter is introduced.

## Roles

| Role | Owns | May not do automatically |
| --- | --- | --- |
| Validator | validation, scoring, receipt verification | change emissions, sign, vote, publish |
| Maintainer | private repository analysis and recommendations | comment, merge, label, close, publish review evidence |
| Miner QA | miner protocol/output conformance | score itself, alter miner state, publish raw traces |
| Builder | isolated builds and bounded runs | deploy or access credentials |
| Product | plans and owner proposals | publish, change roadmap/governance state |
| QA | acceptance and regression evidence | bypass a failing gate |
| Scheduler | dispatch, leases, recovery | grant permissions or perform an owner action |
| Security QA | defensive adversarial testing and remediation proposals | exploit third parties, disclose findings, mutate production |

“Exploit agent” is therefore implemented as **security QA**: it performs
authorized, defensive attack simulation in isolated environments and proposes
containment. It does not receive an offensive execution capability.

## Owner boundary

The factory has no automatic capability for:

- wallet/key access or signing;
- Bittensor transactions, emissions changes, or governance votes;
- GitHub writes: comments, labels, reviews, closes, merges, releases, or
  permission changes; and
- public communication or publication.

An agent can prepare a commitment-bound `ActionIntent` for such work. The
intent contains digests of the payload and rationale, not an execution handle.
`FactoryPolicy.can_auto_execute(...)` is always false. A later owner-action
adapter requires its own proposal, signer separation, explicit approval,
idempotency design, audit policy, and rollback/containment plan.

## Memory contract

Every memory item has both a role scope and an artifact class.

| Scope | Intended use | Cross-role transfer |
| --- | --- | --- |
| `role-private` | raw private operational material | never |
| `shared-commitment` | bounded, shaped coordination facts | commitment-only |
| `publishable-commitment` | externally verifiable public-safe fact | commitment-only |

Private maintainer review material remains `role-private`. It cannot cross into
another role, an HTTP response, a benchmark artifact, a Polaris receipt, a
GitHub comment, or public status. A validator may create a narrow public-safe
commitment, but the policy does not give it publication authority.

`openvang/memory.py` makes the role boundary durable for factory work. A
`FactoryMemoryVault` accepts role-private JSON only through an
operator-supplied authenticated cipher, binds ciphertext to the record id,
role, and plaintext commitment, and keeps an append-only owner-only SQLite
store. Reading requires the same role; a wrong key, altered ciphertext, or
altered binding fails closed. The default package does not invent or persist a
key: deployments using the local Fernet implementation install
`vanguarstew[private-memory]` and supply their key through a secret manager or
other operator-controlled channel.

Cross-role memory in this vault accepts only an already-shaped SHA-256
commitment. It has no API to derive a shared fact from a private record. This
prevents private reviewer material—including its existence, content, reasoning,
or source trace—from being promoted into another role's memory or any public
surface.

This builds on the existing Vanguarstew memory rule: live and benchmark memory
remain separate, benchmark views are time-safe, and raw memory is excluded from
attestation evidence.

## Initial implementation

`openvang/factory.py` declares all eight role contracts and checks:

1. every role has a least-privilege action set;
2. no role can gain an owner-level action;
3. only the validator can create a publishable memory commitment;
4. cross-role exchange excludes role-private artifacts; and
5. public shapes are commitment-only and no role can publish them directly.

It deliberately has no Bittensor SDK, signer, wallet, GitHub-write client,
public webhook, or remote execution dependency.

`openvang/scheduler.py` is the first private control-plane primitive. It stores
only opaque task/output commitments, target role, allowed action, output scope,
budget units, status, and a bounded worker lease in an owner-only SQLite file.
It cannot execute work or expose a task through a network interface.

`openvang/isolated.py` is the first non-privileged adapter. It accepts only a
live leased `run-isolated` task for miner QA, builder, QA, or security QA. Its
input commitment, the owner-supplied approval digest, and an exact
`SealedExecutionPlan` must all match. It delegates only to the existing sealed
executor with its fixed resource and network boundary, independently checks the
aggregate-only result contract, and writes just an output digest back to the
scheduler. It has no shell-command interface, remote executor, credential
access, GitHub client, public output, or cross-role-memory access.

The adapter is deliberately local and operator-invoked for now. A worker must
claim a lease that covers the approved execution time; a stale or hand-built
task is rejected before the sealed executor starts. Its result receipt is a
local commitment, not a Polaris receipt, publication, or proof of workload
confidentiality.

`openvang/subnet.py` provides the next adapter boundary without embedding a
Bittensor client. It accepts an injected, separately reviewed read-only source
and a fixed `subnet-state-v1` projection: network, netuid, block height, and
participant/validator counts. The source cannot return hotkeys, wallet data,
endpoints, weights, prompts, or arbitrary fields through this adapter. A live
validator, miner-QA, or product task is bound to the exact request commitment;
only the normalized snapshot digest is retained. The operator remains
responsible for the source endpoint, credentials (if any), and independently
enforcing that it has no write capability.

Inspect the static contract locally:

```bash
vanguarstew factory-policy
```

This command is informational only. It does not load runtime configuration or
secrets, inspect memory, contact a subnet, or authorize an action.

## Rollout sequence

1. Run the policy registry and commitment-only scheduler beside the current
   Vanguarstew runtime in dry-run mode and record only aggregate
   authorization-denial telemetry locally.
2. Attach one non-privileged adapter at a time: local isolated build/QA and a
   strict read-only subnet-state boundary are available; a live Bittensor
   source still requires separate deployment review. A worker claims only work
   assigned to its role.
3. Pilot one subnet with a fixed budget and an independent validator/QA check.
4. Only after an operator workflow and threat model are approved, consider a
   narrowly scoped owner-action adapter. It must use external signing and a
   human approval step; no general owner key enters the factory.

The existing 24/7 Vanguarstew runtime remains a private maintainer-assist
component within this architecture. It is not promoted to a subnet-wide owner
agent by this policy scaffold.
