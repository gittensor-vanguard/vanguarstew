# Product runtime plan

## Goal

Turn Vanguarstew from an operator-run development tool into a self-hosted
maintainer-assist service that survives restarts, is straightforward to deploy,
and preserves the project's strict private-review boundary. The product keeps
the existing `solve(...)` contract and benchmark/TEE systems separate from
live operations.

The first deliverable is a private control plane. It accepts work, stores
private results locally, and exposes only loopback health checks. It does not
post a review, merge, label, close, reopen, or otherwise mutate GitHub.

## Security and publication contract

| Data | Runtime handling | Public output |
| --- | --- | --- |
| GitHub token, webhook secret, model key | environment only; never JSON config, logs, or status | never |
| PR diff, model prompt, review result, private review evidence | owner-only local result directory | never |
| Runtime queue and heartbeat | owner-local SQLite | never |
| `/healthz`, `/readyz` | loopback-only operational endpoints | static health state only |
| Benchmark / Polaris TEE evidence | independent benchmark pipeline | existing receipt-safe commitments only |

Live review data must never be copied into benchmark artifacts, Polaris receipts,
leaderboards, GitHub comments, or the runtime HTTP response. A public result
requires a separate, explicit publication design and review; it is outside this
runtime plan.

## Delivery phases

1. **Private local foundation — implemented now.** `vanguarstew init`,
   `doctor`, `run-once`, and `serve`; env-only secrets; durable SQLite work
   queue; owner-only review files; read-only GitHub client; signed webhook
   intake; loopback health probes; Compose and systemd templates.
2. **Controlled live pilot.** Configure one repository and a least-privilege
   GitHub App/read token. Enable inference explicitly, keep outputs local, and
   observe cost, queue latency, retries, and failure classes. No automatic
   GitHub write action.
3. **Operator workflow.** Add an authenticated private operator console or
   explicit command for a maintainer to inspect and selectively publish a
   bounded, policy-approved summary. This must not reveal private reviewer
   purpose, evidence, or reasoning traces.
4. **Scale and recovery.** Move queue ownership to a managed database only if
   the local SQLite deployment has demonstrated a real capacity limit; add
   encrypted backup/restore drills, metrics with aggregate-only telemetry, and
   key rotation.
5. **Optional automation.** Any GitHub write capability needs a separate
   threat model, GitHub App permission review, idempotency contract, audit
   controls, and an explicit maintainer approval gate. It is not enabled by
   this implementation.

## Operator flow

```bash
cp .env.example .env
cp vanguarstew.json.example vanguarstew.json
python -m pip install -e .
vanguarstew doctor
vanguarstew serve
```

The copied configuration is intentionally inert: dry-run mode is on and polling
is off. `doctor` makes the state visible without making a network request and
without printing any secret. For a controlled pilot, the operator must make all
three conscious changes in `.env`:

```dotenv
VANGUARSTEW_DRY_RUN=false
VANGUARSTEW_ALLOW_EXTERNAL_INFERENCE=true
VANGUARSTEW_POLL_ENABLED=true
```

They must also provide `VANGUARSTEW_GITHUB_TOKEN`, `VANGUARSTEW_MODEL`,
`VANGUARSTEW_API_BASE`, and `VANGUARSTEW_API_KEY`. The GitHub integration is
read-only; completing a local review still causes no GitHub mutation.

For a service manager, use either `docker compose up -d` (the port remains
bound to `127.0.0.1`) or adapt `deploy/systemd/vanguarstew.service`. Keep the
data directory, `.env`, configuration, and journal private to the operator.

## Operational checks

- `vanguarstew doctor` must pass before starting the service.
- `curl http://127.0.0.1:8080/healthz` and `/readyz` are the only intended
  unauthenticated monitoring probes. Neither identifies a repository, PR, or
  review outcome.
- Inspect `data/private-review-results/` only on the host; it is deliberately
  not an API route.
- Keep `VANGUARSTEW_DRY_RUN=true` for installation and upgrades. Explicitly
  enable live inference only after validating the selected model provider's
  data-handling terms and spend limit.
- The queue uses delivery/head identifiers to make repeated webhook delivery or
  poll cycles harmless. Failed work remains locally visible as a failure class,
  not as a published review trace.
- Work deferred by dry-run or disabled inference returns to the queue only when
  the operator explicitly enables live private inference. A crashed in-progress
  claim is retried only after its 15-minute lease expires; hard failures are not
  retried automatically.

## Acceptance gates for the first live pilot

1. A fresh host can complete the operator flow from an empty data directory.
2. Restarting the process retains queued and completed state without duplicating
   a delivery.
3. A valid signed webhook queues at most one review; an invalid signature
   exposes no payload and creates no work.
4. A dry run produces no network requests and no inference invocation.
5. No endpoint, log line, benchmark artifact, or GitHub action exposes review
   content or creates a GitHub mutation.
6. A local review result is owner-readable only, and the service still exposes
   only health/readiness status.

## Non-goals for this phase

- Replacing the validator-facing `solve(...)` entrypoint.
- Treating Polaris as a confidentiality layer. Polaris remains an integrity
  receipt path for supported benchmark jobs, not a store for live review data.
- Auto-merge, auto-close, auto-label, comment posting, or participant scoring.
- Claiming memory improves live quality before an independently held-out,
  preregistered ablation passes its declared gate.
