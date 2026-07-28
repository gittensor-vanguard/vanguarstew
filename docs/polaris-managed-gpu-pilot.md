# Polaris managed GPU pilot

The first GPU milestone is a public, non-secret integrity pilot. Polaris documents a managed
Hybrid GPU request on the persistent TDX sandbox API. The TDX box drives a commodity GPU, records
the run, and folds the latest record into a fresh re-attestation receipt.

This path targets execution integrity and provenance. It does not protect GPU memory, prove timing,
or make a confidentiality claim. Anything sent to the GPU must be treated as visible to its
operator.

## Offline managed-sandbox plan

Use a fresh, dedicated Ed25519 SSH key. Select the exact `name`, provider, availability, and spot
price from the live `GET /api/v2/compute/gpus` response, then bind rate caps into the plan:

```bash
python -m scripts.plan_managed_gpu_sandbox \
  --ssh-public-key-file /path/to/fresh-key.pub \
  --name gpu-worker-1 \
  --gpu-type 'RTX PRO 6000 96GB' \
  --max-gpu-hourly-usd 1.32 \
  --max-pairing-premium-hourly-usd 0.15 \
  --max-spend-usd 1.00 \
  --max-runtime-minutes 30
```

Planning is network-free. The approval digest binds the exact sandbox request, catalog caps,
expected runtime rate bound, no-retry rule, polling/status checks, and unconditional stop policy.
The public request disables agents, inbox/email, Bittensor primitives, and attested secrets. It
uses spot capacity and `auto_stop=true`.

`PolarisGpuClient.create_managed_approved(...)` performs one billing eligibility check and one live
catalog check before creation. It aborts before the billable request if the account is ineligible,
the selected item is unavailable or ambiguous, or either rate exceeds its approved cap. The
sandbox's `max_spend_usd` remains the provider-enforced hard guardrail. A timeout or malformed
create response must be recovered by listing owner-scoped sandboxes and matching the unique neutral
name; never retry creation blindly.

## Discovery before workload execution

The initial live run should stop after these bounded checks unless every stage succeeds:

1. poll only owner-scoped sandbox detail until TDX attestation is ready;
2. verify and privacy-scan the boot receipt;
3. inspect `GET /api/v2/sandbox/:id/gpu` without logging connection fields;
4. connect with the fresh key and an explicitly pinned SSH host key;
5. inspect the installed `polaris-gpu --help` contract; and
6. stop the sandbox on success, failure, timeout, or uncertainty.

The GPU command and re-attestation require separate exact approvals after the live tool contract is
known. A fresh re-attestation plan binds the sandbox identifier through SHA-256, the nonce, endpoint,
body, and zero-retry rule.

## Receipt boundary

Polaris says the re-attested receipt gains a `gpu_provenance` object, but its nested JSON schema is
not currently documented. `inspect_gpu_provenance_schema(...)` returns only structural paths and
types and always reports `verification_supported=false`. Presence is not proof. A verifier may be
added only after an observed receipt schema and its digest/egress semantics are reviewed; it must
fail closed on any unknown version or field meaning.

Keep complete owner responses, connection metadata, keys, and receipts in mode-`0600` local files.
Do not publish a receipt until its provider identifiers and correlation fields have received a
separate privacy review.
