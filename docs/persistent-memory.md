# Persistent memory

Vanguarstew can use validated, repository-scoped memory without changing the public
`solve(repo_path, request, model, api_base, api_key, n)` contract. The feature is owned by the
validator/controller layer; agent code receives a small, read-only `memory_view` only through the
frozen context it already reads.

## Modes

| Mode | Purpose | Source of truth |
| --- | --- | --- |
| `disabled` | Stateless replay. This is the default. | Deterministic empty view. |
| `live` | Long-lived maintainer knowledge. | Owner-local SQLite controller. |
| `benchmark` | Historical replay without future leakage. | Fresh task-scoped snapshot at or before the task freeze time. |

Benchmark mode is deliberately not shared across tasks. Every task constructs a new snapshot,
filters events by its own freeze time, and sends no state back to the store. Running tasks in a
different order therefore cannot change any view or commitment.

## Trust boundary

The controller stores append-only events in SQLite and uses FTS5/BM25 only after filtering by
repository, role, authority, publication class, status, expiry, namespace, and time boundary.
Events retain source references, timestamps, confidence, creation method, agent/policy version,
content digest, and supersession/tombstone links.

Untrusted external, model, or tool text starts as a quarantined observation. It must be promoted by a
trusted controller before recall. Recalled text is labeled evidence, not an instruction. The
controller keeps coordination memory structurally separate from quality decisions such as review,
merge, close, score, or tier.

The agent never receives a database path, credentials, mutation API, raw snapshot, or controller
state. It receives at most 50 bounded evidence items in a deterministic `MemoryView`.

## Public boundary and attestation

Public benchmark and attested-evaluation paths use publishable memory only. A run artifact and
TEE evidence can contain only these commitments:

- memory schema version and policy version;
- filtered snapshot root;
- query digest; and
- final view digest.

Raw recalled content, source evidence, snapshots, store files, and controller state are excluded
from attestation evidence and the leaderboard feed. The public-feed formatter independently
normalizes the commitment shape, so a malformed direct caller cannot widen this surface.

## Controller usage

The trusted controller, not the agent, owns the store. A live flow creates a view and writes it
into the trusted frozen context before calling the unchanged entrypoint:

```python
from benchmark.memory import LiveMemoryProvider, MemoryStore, attach_memory_view

with MemoryStore("/controlled/memory.sqlite") as store:
    provider = LiveMemoryProvider(store, repository_id="owner/repo")
    view = provider.view(request="review this change", purpose="review")
    agent_context = attach_memory_view(frozen_context, view)
    # Write agent_context into the read-only task checkout, then invoke solve(...) normally.
```

The default live provider recalls publishable knowledge only. A controller that needs non-public
evidence must opt in explicitly and keep the resulting workflow non-public.

## Benchmark usage

The direct API accepts a `BenchmarkMemoryProvider`; it creates a fresh snapshot on each replay
task. `run_replay` rejects a memory view unless it is benchmark-mode, publishable-only, and exactly
matches the task's freeze timestamp.

For a single-repository local replay:

```bash
VANGUARSTEW_OFFLINE=1 python -m scripts.run_eval \
  --repo /path/to/repo \
  --memory-mode benchmark \
  --memory-store /controlled/memory.sqlite \
  --memory-repository-id owner/repo \
  --tasks 2 --horizon 5
```

The attested public evaluator exposes the same opt-in with `--memory-mode benchmark` and
`--memory-store`; it derives the repository identity from its required public repository argument.

## Verification

`tests/test_persistent_memory.py` covers append-only storage, promotion, filtering, expiration,
supersession, deterministic retrieval, task isolation, freeze-time checks, prompt bounds, and
receipt-safe commitments. Runner, attestation, public-feed, and CLI tests verify the integration
boundaries.

For a local, paired proof of whether a source-anchored benchmark memory view improves the same
frozen tasks, see the [memory ablation protocol](memory-ablation.md). It has a predeclared
significance gate and does not publish source evidence or memory contents.
