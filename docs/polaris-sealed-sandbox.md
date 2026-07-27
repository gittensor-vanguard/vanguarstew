# Polaris sealed sandbox

Polaris documents `POST https://api.polaris.computer/api/v2/sandbox` as the persistent Intel TDX
surface with SSH access. This is distinct from `POST https://polaris.computer/v1/attest`, which
runs one command or image and returns a one-shot proof receipt.

This integration plans a bare sandbox. It deliberately cannot include a container image, preload
an agent, provision an inbox, enable email or Bittensor primitives, or request attested-secret
injection. The workload is transferred separately over the authenticated SSH connection after the
box passes its privacy gate.

## Offline plan

Generate a fresh Ed25519 key for the sandbox or select an existing dedicated public key. Then render
the exact request without loading a Polaris API key or making a network request:

```bash
python -m scripts.plan_polaris_sandbox \
  --ssh-public-key-file /path/to/dedicated-key.pub \
  --name sealed-worker-1 \
  --max-spend-usd 1.00 \
  --max-runtime-minutes 60
```

The planner strips the SSH key comment and emits the request plus `request_sha256`. Review both.
Sandbox creation is a potentially billable external-state change and must receive explicit
approval for that exact digest before `PolarisSandboxClient.create_approved` is called. A changed,
missing, or malformed approval digest fails before network access.

## Privacy gate

Polaris documents a public boot-receipt route for every sandbox. Before any private workload is
transferred:

1. Create only a neutral empty sandbox with a non-identifying name.
2. Keep the sandbox ID, connection details, and receipt URL out of logs and public artifacts.
3. Inspect the boot receipt privately for names or metadata that identify workload purpose,
   operators, infrastructure, or inputs.
4. Stop the sandbox immediately if the receipt crosses that boundary.

The adapter does not claim that an unguessable public receipt is private. Production use remains
blocked until the receipt contents are confirmed compatible with the project's privacy policy or
Polaris offers an authenticated/private receipt mode.

### Exact boot-receipt verification

Read the receipt only from Polaris's documented JSON route:

`GET https://api.polaris.computer/api/v2/compute/instances/:id/receipt`

Do not treat an opaque `receipt_id` as a relative URL, follow an unvalidated receipt URL, or accept
an HTTP 200 HTML page as proof. `PolarisSandboxClient.boot_receipt(id)` fixes the host and route and
requires a JSON object. `verify_boot_receipt(...)` checks the ready/verified states, quote and report
data shapes, decodes the receipt's `pubkey_b64`, verifies it is the normalized customer SSH public
key, and independently recomputes the customer-key half of TDX `report_data`.

The public receipt deliberately contains a reversible base64 representation of that customer key.
Use a fresh key for every sandbox, never reuse it for another service or sandbox, and never attach
an identifying comment. The key is not secret, but reuse would create a durable correlation handle.
`inspect_boot_receipt_privacy(...)` scans both ordinary receipt strings and reversible base64 fields
for caller-supplied forbidden terms without returning the terms or matched values.

## Live lifecycle boundary

`benchmark.polaris_sandbox.PolarisSandboxClient` exposes only:

- `create_approved(plan, approved_request_sha256=...)` for the exact reviewed request;
- `detail(id)` for owner-scoped polling without implicit logging; and
- `stop_approved(id, approved_sandbox_id=...)` for an explicitly matched stop target.

The client reads a permission-restricted dotenv file without sourcing it, redacts its key from
`repr`, bounds response sizes, discards error bodies, validates IDs before URL construction, and
does not print returned connection metadata. Operator tooling must save any complete create/detail
response only to a new mode-`0600` local file and must never commit it.

SSH onboarding at `ssh polaris@ssh.polaris.computer` is only an API-key gateway. It is not a shell
on the sandbox. An account that already has a Polaris API key does not need to repeat onboarding.

## Pinned SSH staging boundary

A successful boot receipt does **not** bind the SSH server host key, code uploaded after boot, a
remote command, or its output. It proves the TDX boot and customer-key binding. The current Polaris
documentation does not provide an attested SSH host-key field, so the operator must explicitly
accept the control-plane/host-key trust decision; do not describe this as cryptographic channel
binding to the receipt.

`benchmark.sealed_ssh` stages a payload only when all of these conditions hold:

- the identity, `known_hosts`, and bundle are non-empty regular files inaccessible to group/others;
- `known_hosts` is already populated and SSH uses `StrictHostKeyChecking=yes` (never `accept-new`);
- agent forwarding, port forwarding, local commands, and TTY allocation are disabled;
- the bundle is at most 64 MiB and its bytes still match the offline-approved SHA-256;
- the fresh result challenge and aggregate contract are included in the approved plan digest; and
- staging performs one upload plus a remote SHA-256 check, without extraction or execution.

Render a connection-free staging plan locally:

```bash
python -m scripts.plan_sealed_ssh \
  --bundle /path/to/mode-0600-payload.tar \
  --challenge <fresh-64-lowercase-hex>
```

The plan intentionally omits the local path, SSH coordinates, identity path, and known-hosts path.
Staging changes remote state and must receive explicit approval for the exact `request_sha256`.
Extraction and execution remain separate, unimplemented operations requiring their own review.

## Aggregate-only result contract

Never copy a full multi-repository replay artifact across the sealed boundary: it can contain repo
identities, paths, task rows, diagnostics, and model text. `benchmark.sealed_aggregate` constructs a
new canonical envelope from an allowlist rather than attempting to redact the original artifact.
The only wire fields are:

- contract version and a fresh 32-byte challenge;
- scored and skipped repository counts; and
- composite, judge, and objective means as bounded integer millionths.

There are no free-form strings, per-repository entries, task rows, paths, errors, commits, input
hashes, or extension fields. The verifier rejects extra keys, non-canonical JSON, booleans/floats on
the wire, invalid ranges, and a challenge mismatch. Inside the sealed machine, pipe the complete
artifact through stdin so its path is not part of the command contract:

```bash
python -m scripts.emit_sealed_aggregate --challenge <fresh-64-lowercase-hex> < result.json
```

This aggregate envelope limits what leaves the workload; it does not make the SSH result attested.
End-to-end workload proof requires a future protocol that binds uploaded code, inputs, and canonical
output into a fresh quote.
