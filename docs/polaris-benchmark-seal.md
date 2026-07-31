# Polaris benchmark receipt seal

`benchmark.polaris_benchmark` adds a fail-closed TDX integrity boundary after a dual-target PR
benchmark completes. It is intentionally a one-shot proof workload on `POST /v1/attest`, not an
SSH command inside a persistent sandbox: Polaris documents that the one-shot receipt binds the
workload, mounted inputs, egress policy, and stdout, while a sandbox boot receipt does not bind
later SSH activity.

The seal mounts the combined report, all four raw artifacts (baseline/candidate for the public and
second targets), and a deterministic 64 KiB Python validator archive. Inside the measured one-shot
workload the validator runs every live integrity gate, recomputes each `score_pr_delta` report,
recombines the conservative decision, and verifies the report evidence and PR bindings. Only then
does it emit canonical public-safe JSON containing the PR/base commit binding, public-target band,
conservative final verdict, and opaque integrity commitments. The request uses `egress=none`.
Local verification checks the caller and freshness binding, shell-workload digest, mounted-file
digest, exact stdout, quote report data, and Polaris's Intel-verification result.

This proves that the receipt-bound validator recomputed the decision from the exact mounted raw
artifacts inside the measured TDX workload. It does **not** claim that hosted model inference ran in
the TEE, that Polaris provides workload confidentiality, or that the Intel chain was independently
verified unless a separate local DCAP verifier succeeds.

Receipt validity is independent of benchmark outcome. A receipt can validly attest a positive,
neutral, or merge-blocking regression result; successful verification means the declared decision
was recomputed from the bound artifacts, not that the candidate passed the benchmark.

## Offline plan

The combined report must be a mode-`0600` regular file. It must contain the public and second
target reports, their recomputable conservative decision, the PR/base commit bindings, and valid
`benchmark.attestation` evidence with a recorded transcript digest.

```bash
python -m scripts.plan_polaris_benchmark \
  --report /private/report.json \
  --baseline-public /private/baseline-public.json \
  --candidate-public /private/candidate-public.json \
  --baseline-private /private/baseline-private.json \
  --candidate-private /private/candidate-private.json \
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
  --baseline-public /private/baseline-public.json \
  --candidate-public /private/candidate-public.json \
  --baseline-private /private/baseline-private.json \
  --candidate-private /private/candidate-private.json \
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

## Public verification evidence

Contract `vanguarstew-benchmark-tee-v3` makes the fixed result envelope useful as public evidence
without publishing protected evaluation inputs. The quote-bound stdout includes:

- the PR number, base ref, base commit, and exact reviewed head commit;
- the public target's policy band and merge-block flag;
- the conservative final band and merge-block flag; and
- opaque report, input-bundle, integrity-gate, and evidence commitments.

After complete local receipt verification, `build_public_benchmark_evidence()` reduces that result
again to a bounded review-comment summary: the public PR binding and outcome, Polaris TDX kind,
verification level, provider Intel/report-data checks, UTC start time, and deterministic validator,
workload, and result commitments. It deliberately omits target identities, per-target measurements,
reports, artifacts, model transcripts, the raw quote/collateral, freshness values, request digest,
requester material, billing data, and infrastructure details.

The summary is verification evidence, not the complete receipt. `polaris-verified` means the local
client verified the complete quote binding and Polaris reported Intel verification; it must not be
described as an independently verified Intel chain unless the separate offline DCAP verifier also
passes with complete collateral and the approved measurement policy.

Re-run the same verification later with the privately retained report and freshness values:

```bash
python -m scripts.verify_polaris_benchmark \
  --receipt /private/receipt.json \
  --report /private/report.json \
  --baseline-public /private/baseline-public.json \
  --candidate-public /private/candidate-public.json \
  --baseline-private /private/baseline-private.json \
  --candidate-private /private/candidate-private.json \
  --nonce <same-64-hex> \
  --e2e-pubkey <same-base64-public-binding>
```
