# Public Polaris TEE pilot

This is the smallest end-to-end integrity prototype: one public, non-secret shell workload, one
public input, one exact output contract, a fresh challenge, and a Polaris TDX receipt. It proves the
receipt pipeline before a higher-cost GPU pilot is attempted.

The claim is intentionally narrow. A passing receipt binds the committed shell code, mounted input,
stdout, no-egress policy, and requester challenge to the TDX quote. It does not claim workload
confidentiality or GPU provenance. Polaris's hybrid GPU flow is the next phase because it also
requires a GPU host and a `gpu_provenance` receipt.

## 1. Plan without network access

Generate a fresh 32-byte nonce and a fresh requester public value. Keep any corresponding private
key out of the repository; the pilot uses only the base64 public value.

```bash
python -m scripts.plan_public_tee_pilot \
  --nonce <fresh-64-hex> \
  --e2e-pubkey <fresh-base64-public-value>
```

The output contains the complete public request, its `request_sha256`, and the receipt contract.
Review it and obtain explicit approval for that exact digest. Planning does not read the API key or
make a request.

## 2. Run exactly once

The dotenv file must be inaccessible to group and other users. The receipt output must not already
exist; the runner creates it with mode `0600`. It does not retry.

```bash
python -m scripts.run_public_tee_pilot \
  --env-file /path/to/mode-0600.env \
  --nonce <same-64-hex> \
  --e2e-pubkey <same-base64-public-value> \
  --approved-request-sha256 <approved-digest> \
  --receipt-output /path/to/new-receipt.json
```

The live command sends only the reviewed public request to `https://polaris.computer/v1/attest`.
It saves the full response locally and prints only a bounded status summary.

## 3. Verify the receipt

Any verifier with the receipt, nonce, and requester public value can recompute the code, input,
stdout, and quote bindings:

```bash
python -m scripts.verify_public_tee_pilot \
  --receipt /path/to/receipt.json \
  --nonce <same-64-hex> \
  --e2e-pubkey <same-base64-public-value> \
  --strict
```

Without `--dcap-policy`, a valid result is labeled `polaris-verified`: the bindings are recomputed
locally, while Intel-chain verification remains Polaris's server-side claim. Supplying a reviewed
local TDX measurement policy enables the existing offline DCAP/QVL path and is required for an
`independently-verified` hardware result.

Do not publish a receipt automatically. Inspect the saved artifact first, then deliberately choose
whether it belongs in a public pilot set. No private evaluation input or operational identifier is
part of this fixed workload.
