# OpenVang architecture

## Component model

OpenVang is one agent factory with explicit specialist roles. The repository
currently carries the maintainer-intelligence component, its benchmark, and a
private runtime. The factory policy is the authority boundary between them.

- **`openvang/` — factory control plane.** Fixed role contracts, memory
  scopes, publication rules, commitment-only owner-action intents, a durable
  private scheduler, an approval-bound local sealed-execution adapter, and a
  strict injected-source contract for read-only subnet snapshots. It has no
  wallet, signer, Bittensor SDK, GitHub-write client, remote executor, or
  public endpoint.
- **`agent/` + `agent.py` — maintainer intelligence.** The fixed `solve()`
  entrypoint and philosophy → plan → decide → implement workflow.
- **`benchmark/` — integrity controller.** Historical replay, judging,
  scoring, attestation, and controller-owned persistent memory.
- **`vanguarstew_runtime/` — private maintainer service.** Durable local queue,
  read-only GitHub intake, local result retention, loopback health checks, and
  no GitHub write path.

## Layout

```
openvang/                       factory authority and memory policy
  factory.py                    eight role contracts and action-intent checks
agent/                          maintainer-intelligence implementation
  llm.py                        managed-inference client
  context.py                    frozen, knowable-at-time repository state
  philosophy.py                 infer repository direction and values
  planner.py                    plan bounded next actions
  decider.py                    make concrete maintainer decisions
agent.py                        fixed solve(repo_path, request, ...) entrypoint
benchmark/                      replay, scoring, memory, and attestation controller
  freeze.py                     build leakage-safe history snapshots
  taskgen.py                    generate replay tasks
  judge.py                      pairwise evaluation
  score.py                      objective scoring anchor
  memory.py                     trusted persistent-memory controller
  runner.py                     replay orchestration
vanguarstew_runtime/            restart-safe private service runtime
scripts/run_eval.py             end-to-end replay CLI
```

## Maintainer-agent contract

The benchmark invokes the maintainer component through a stable interface:

```python
solve(
    repo_path="/tmp/task_repo",
    request="plan next 5 actions",
    model="validator-managed-model",
    api_base="http://validator-proxy/v1",
    api_key="per-run-proxy-token",
)
```

The controller supplies managed inference and a frozen context. The component
does not gain controller credentials, a memory-store handle, or external owner
authority from this call.

## Factory authority model

The factory defines eight roles: validator, maintainer, miner QA, builder,
product, QA, scheduler, and security QA. Each contract lists its non-privileged
actions and readable/writable memory scopes.

No role can automatically access a wallet, submit an on-chain transaction,
change emissions, vote in governance, mutate GitHub, or publish. Such effects
can only be represented as an immutable, commitment-bound owner intent. The
policy always denies automatic execution.

Run `vanguarstew factory-policy` to inspect the static contract. It reads no
runtime configuration or secrets and exposes no live work, reviews, memory, or
subnet state.

## Memory and publication boundaries

Persistent memory is controller-owned and remains distinct between live and
benchmark use. Benchmark retrieval is time-safe at each freeze point; raw
memory is excluded from public artifacts and TEE evidence.

Factory policy adds role-private, shared-commitment, and
publishable-commitment scopes. Role-private content—including private
maintainer-review material—cannot cross role boundaries. Cross-role exchange
is commitment-only. Publication remains an owner action even for a
publishable-safe commitment.

The factory-specific vault is distinct from benchmark persistent memory. It is
an owner-local append-only SQLite store with authenticated encryption for raw
role-private records. It stores only pre-shaped digests for cross-role
coordination and offers no operation that converts a private record into a
shared or public fact. The encryption key is external to the repository and
database; deployments must use an operator-managed secret source.

## Benchmark and TEE boundaries

The benchmark measures the maintainer component against real historical
repository trajectories. It is not a source of owner authority.

Polaris receipts can bind a supported benchmark result to an integrity-checked
execution. They do not make GPU work confidential and must not contain private
review data, raw memory, credentials, or operational identifiers. See
[persistent-memory.md](persistent-memory.md) and
[polaris-benchmark-seal.md](polaris-benchmark-seal.md).

## Deployment evolution

The current private service is suitable for a controlled maintainer-assist
pilot. The first factory adapter binds a live role-specific task and external
approval to the existing network-isolated sealed executor, then retains only a
verified aggregate digest. The next adapter defines a fixed, identity-free
read-only subnet-state projection but deliberately leaves its live data source
outside the factory. Any later owner-action gateway must be a separately
reviewed system with external signing, exact approvals, idempotency, and
rollback/containment controls.
