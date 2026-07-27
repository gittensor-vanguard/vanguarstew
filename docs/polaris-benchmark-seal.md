# Polaris benchmark receipt seal

`benchmark.polaris_benchmark` adds a fail-closed TDX integrity boundary after a dual-target PR
benchmark completes. It is intentionally a one-shot proof workload on `POST /v1/attest`, not an
SSH command inside a persistent sandbox: Polaris documents that the one-shot receipt binds the
workload, mounted inputs, egress policy, and stdout, while a sandbox boot receipt does not bind
later SSH activity.

The seal validates the combined benchmark decision, PR base/head bindings, and recorded-transcript
evidence locally. It canonicalizes the complete report, divides it into at most eight 256 KiB
mounted files, and renders a shell workload that hashes the concatenated bytes before emitting one
fixed JSON decision. The request uses `egress=none`. Local verification then checks the caller and
freshness binding, shell-workload digest, mounted-file digest, exact stdout, quote report data, and
Polaris's Intel-verification result.

This proves that the exact benchmark report and fixed decision passed through the measured TDX
workload. It does **not** claim that hosted model inference ran in the TEE, that Polaris provides
workload confidentiality, or that the Intel chain was independently verified unless a separate
local DCAP verifier succeeds.

## Offline plan

The combined report must be a mode-`0600` regular file. It must contain the public and second
target reports, their recomputable conservative decision, the PR/base commit bindings, and valid
`benchmark.attestation` evidence with a recorded transcript digest.

```bash
python -m scripts.plan_polaris_benchmark \
  --report /private/report.json \
  --nonce <fresh-64-hex> \
  --e2e-pubkey <base64-public-binding>
```

The plan reveals only bounded sizes, digests, and the aggregate decision. It does not print the
report, repository identities, PR number, commit IDs, model transcript, or requester key. Review
the exact `request_sha256` before any live call.

## Approved run

```bash
python -m scripts.run_polaris_benchmark \
  --env-file /private/polaris.env \
  --report /private/report.json \
  --nonce <same-64-hex> \
  --e2e-pubkey <same-base64-public-binding> \
  --approved-request-sha256 <approved-digest> \
  --receipt-output /private/new-receipt.json
```

The runner makes exactly one request and has no retry loop. The complete response is reserved as a
new mode-`0600` file before network access and is never printed. An approval mismatch, malformed
report, transport failure, missing receipt binding, changed output, or failed verification exits
nonzero. Automation must treat that as an unavailable benchmark and must not apply a performance
decision from the unsealed report.

Full reports, receipts, receipt URLs, requester material, and operational approval digests are
private artifacts. Public review comments may use only the repository's separately defined
aggregate disclosure policy; this tool never publishes anything.

Re-run the same verification later with the privately retained report and freshness values:

```bash
python -m scripts.verify_polaris_benchmark \
  --receipt /private/receipt.json \
  --report /private/report.json \
  --nonce <same-64-hex> \
  --e2e-pubkey <same-base64-public-binding>
```
