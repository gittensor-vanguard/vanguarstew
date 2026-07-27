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
Extraction and execution use a separate plan and approval digest described below.

## Deterministic sealed bundle

`benchmark.sealed_bundle` packages a mode-`0700` source directory into a deterministic uncompressed
tar archive. The source must contain an executable `run` file; the archive always renames that fixed
entrypoint to `payload/run`. Every source directory and file must be inaccessible to group/others.
Links, devices, sockets, empty/oversized inputs, output paths inside the source tree, and more than
1,024 files are rejected.

The first archive member is a canonical `manifest.json`; all remaining members are sorted regular
files below `payload/`. The manifest binds each path, byte length, normalized mode, and SHA-256, plus
the aggregate result contract. Archive timestamps, owners, group names, links, and extension fields
are forbidden. Extraction validates the complete archive and writes each file with exclusive,
no-follow operations; it never calls `tarfile.extract`.

```bash
python -m scripts.package_sealed_bundle \
  --source /path/to/mode-0700-source \
  --output /path/to/new-mode-0600-bundle.tar
```

The command refuses to overwrite an existing output. Its JSON response contains only the bundle
digest, bounded sizes, and file count; it does not print source paths or member names.

## Approval-bound extraction and execution

First render a network-free plan from the exact staged bundle and a fresh result challenge:

```bash
python -m scripts.plan_sealed_execution \
  --bundle /path/to/staged-bundle.tar \
  --challenge <fresh-64-lowercase-hex> \
  --timeout-seconds 900 \
  --max-output-bytes 8388608 \
  --max-memory-bytes 1073741824
```

The plan binds the bundle digest and size, challenge, timeout, output and memory limits, namespace
policy, filesystem limitation, and aggregate contract into a new `request_sha256`. It omits the
bundle's local path and member names. Execution is a separate external-state action and requires
explicit approval for that exact digest:

```bash
python -m scripts.run_sealed_bundle \
  --bundle /path/to/staged-bundle.tar \
  --challenge <same-64-lowercase-hex> \
  --timeout-seconds 900 \
  --max-output-bytes 8388608 \
  --max-memory-bytes 1073741824 \
  --approved-request-sha256 <approved-plan-digest>
```

The executor refuses host-root operation. It revalidates the approved bundle, extracts into a new
mode-`0700` temporary workspace, and launches `payload/run` through the system `unshare` binary in
fresh user, network, IPC, UTS, mount, and PID namespaces. The child verifies that only loopback is
visible before execution. User-provided stdin, inherited environment variables, credentials, agent
forwarding, and network interfaces are absent. Runtime, address space, output file size, open file
descriptors, and core dumps are bounded. Workload stderr is discarded; its stdout goes to a
mode-`0600` bounded file and is never forwarded directly.

After a successful exit, the parent parses the captured artifact and constructs the aggregate-only
envelope. Any failure emits one constant diagnostic. The extracted workspace, captured artifact,
temporary home, and scratch directory are removed on both success and failure; the content-addressed
staged bundle remains for separately approved cleanup.

This protocol minimizes egress and output for trusted application code; it is not an adversarial
filesystem sandbox. The new mount namespace initially sees the host mounts, and a deliberately
malicious payload could read or write files its SSH account can access or encode data into allowed
aggregate scalars. Keep the sealed account free of unrelated files and credentials. The Polaris
boot receipt still does not bind the uploaded bundle, command, or output, so this must not be called
end-to-end workload attestation.

## Target-bound remote invocation

The bare sandbox does not inherit the local checkout that contains the executor. Build a
deterministic, mode-`0600` Python zipapp containing only the fixed public executor modules and its
network-namespace helper:

```bash
python -m scripts.package_sealed_runtime \
  --output /path/to/new-mode-0600-runtime.pyz
```

The packager requires a clean, tracked executor allowlist and binds the exact public Git revision.
It uses a canonical manifest, stored ZIP members, normalized metadata, and exclusive output
creation. Inspection requires the archive to byte-match the executor source in that checkout;
adding or changing a module fails planning. The runtime verifies its own approved digest before it
extracts the fixed helper into a temporary private directory.

Remote execution assumes the payload was already staged with `SealedSSHTransport` at its
content-addressed path. Save the owner-scoped sandbox detail response in a mode-`0600` file and
render a network-free plan:

```bash
python -m scripts.plan_sealed_remote \
  --owner-detail-file /path/to/mode-0600-owner-detail.json \
  --known-hosts-file /path/to/mode-0600-known-hosts \
  --runtime /path/to/mode-0600-runtime.pyz \
  --bundle /path/to/mode-0600-payload.tar \
  --challenge <fresh-64-lowercase-hex> \
  --timeout-seconds 900 \
  --max-output-bytes 8388608 \
  --max-memory-bytes 1073741824
```

The plan hashes the sandbox ID, documented SSH target fields, and exact pinned `known_hosts` contents
into an opaque target binding. Raw connection metadata, the ID, host key, local paths, and runtime
member names are omitted. Keep the plan and target-binding digest private because they identify one
operational approval. The request binds the target, runtime, payload, execution limits, challenge,
inner execution digest, aggregate contract, and exact cleanup policy into a new `request_sha256`.

After explicit approval for that exact request, invoke it through the already pinned SSH channel:

```bash
python -m scripts.run_sealed_remote \
  --owner-detail-file /path/to/mode-0600-owner-detail.json \
  --identity-file /path/to/mode-0600-identity \
  --known-hosts-file /path/to/mode-0600-known-hosts \
  --runtime /path/to/mode-0600-runtime.pyz \
  --bundle /path/to/mode-0600-payload.tar \
  --challenge <same-64-lowercase-hex> \
  --timeout-seconds 900 \
  --max-output-bytes 8388608 \
  --max-memory-bytes 1073741824 \
  --approved-request-sha256 <approved-remote-plan-digest>
```

The transport first checks that the target and connection match the approved binding. It verifies
the already-staged payload hash and private mode, uploads only the content-addressed public runtime,
hash-checks it remotely, and invokes it with a minimal environment and the separately bound inner
execution approval. SSH stderr is discarded and stdout is capped at 4 KiB before the aggregate
schema and challenge are verified locally. Success returns only the canonical aggregate envelope.
Failure returns one constant diagnostic.

The final SSH command removes only the exact content-addressed runtime, payload, and upload paths;
cleanup is attempted after both success and failure, and a cleanup failure suppresses the result.
Connection loss can still prevent cleanup, so sandbox stop remains the final lifecycle boundary.

Polaris documents on-demand re-attestation with a fresh nonce, but does not document a generic
binding from arbitrary SSH-uploaded files, commands, or stdout into that quote. The opaque target
binding is an operator approval control, not a hardware claim. The boot receipt and any later quote
must not be described as binding this runtime, payload, command, or aggregate.

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
