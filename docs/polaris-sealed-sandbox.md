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
