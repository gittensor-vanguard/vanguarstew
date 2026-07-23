# Spec 075 — attestation evidence binding

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1967
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/attestation.py`](../../benchmark/attestation.py) (the module under test),
  [`benchmark/transcript.py`](../../benchmark/transcript.py) (`digest`, the sha256-of-canonical-JSON
  primitive it binds with)

This spec makes the **existing, implicit** attestation-binding contract explicit. It describes the
as-built behavior of `benchmark/attestation.py`; it introduces **no behavior change**.

## `digest` (imported primitive)

`benchmark.transcript.digest(value)` returns the `sha256` hex string (64 lowercase hex chars) of a
canonical JSON encoding of `value` — deterministic (key order does not matter) and collision-
resistant. This spec relies only on those properties: equal inputs give equal digests, and any
change to the bound content changes the digest. Tests exercise the real `digest`, not a mock.

## Why

A TEE quote alone proves "some attested enclave ran the expected image" — not the claim that
matters: *this enclave, running this image, produced THIS score against THESE inputs*. The score
must be cryptographically bound into the quote's caller-supplied `report_data` field.
`build_evidence` computes what goes in that field over `(inputs, artifact)`; `verify_evidence`
checks the binding afterwards and says precisely which link failed.

## User stories

1. **As a verifier**, I can recompute an evidence bundle from a published artifact + inputs and
   confirm its `report_data` matches, so a quote is a statement about a specific, fully-described run.
2. **As an auditor**, I get a per-check report distinguishing an edited-after-the-fact artifact
   (`artifact_digest` mismatch) from a quote that attests a different run (`quote_binding` mismatch).
3. **As a reviewer**, the input-field restriction, the offline (no-quote) path, and the malformed
   -input branch are written down (addressing the incompleteness class of rejection seen on Specs
   057/059).

## Constants

- `EVIDENCE_VERSION` SHALL be `1`.
- `_INPUT_FIELDS` SHALL be exactly `("repo_set", "repo_set_partition", "seed", "rotation_seed",
  "model", "agent_commit", "eval_image", "transcript_digest")`.

## Acceptance criteria (EARS)

### `build_evidence(artifact, inputs)`

- WHEN `inputs` is not a dict THEN it SHALL log a `logging.warning` on the module logger
  `benchmark.attestation` (`attestation: inputs is {type}, not a dict; treating as empty`) and treat
  `inputs` as `{}`.
- The returned bundle SHALL carry exactly the keys `version`, `inputs`, `artifact_digest`,
  `report_data`.
- `version` SHALL be `EVIDENCE_VERSION`.
- `inputs` SHALL be a dict with exactly the `_INPUT_FIELDS` keys, each set to `inputs.get(field)`
  (so an absent field is `None`); any key **not** in `_INPUT_FIELDS` SHALL be dropped, never
  changing the binding.
- `artifact_digest` SHALL be `digest(artifact)`.
- `report_data` SHALL be `digest({"inputs": bound_inputs, "artifact_digest": artifact_digest})`.
- `build_evidence` SHALL be deterministic: equal `(artifact, inputs)` SHALL give an equal bundle,
  and a change to any bound input field or to the artifact SHALL change `report_data`.

### `verify_evidence(artifact, evidence, quote_report_data=None)`

- WHEN `evidence` is not a dict THEN it SHALL return exactly
  `{"ok": False, "checks": {"evidence_shape": False}, "detail": "evidence is {type}, not a dict"}`
  (and SHALL NOT carry `quote_checked`/`expected_report_data`).
- OTHERWISE it SHALL recompute `build_evidence(artifact, evidence.get("inputs"))` and populate
  `checks`:
  - `checks["artifact_digest"]` SHALL be `evidence.get("artifact_digest") == recomputed
    artifact_digest`;
  - `checks["report_data"]` SHALL be `evidence.get("report_data") == recomputed report_data`;
  - WHEN `quote_report_data is not None` THEN `checks["quote_binding"]` SHALL be
    `quote_report_data == recomputed report_data`; WHEN it is `None` the quote check SHALL be
    **skipped** (absent from `checks`), not failed.
- `ok` SHALL be `all(checks.values())`.
- `quote_checked` SHALL be `quote_report_data is not None`.
- `expected_report_data` SHALL be the recomputed `report_data`.
- `detail` SHALL be `"all checks passed"` when every check passed, else `"; ".join` of
  `"{name} FAILED"` for each failing check, in `checks` insertion order.
- Round-trip: `verify_evidence(artifact, build_evidence(artifact, inputs))` SHALL have `ok is True`
  with `checks == {"artifact_digest": True, "report_data": True}` and `quote_checked is False`; and
  supplying that bundle's `report_data` as `quote_report_data` SHALL additionally pass
  `quote_binding` with `quote_checked is True`.

### Failure localization

- An edited artifact (verifying `evidence` built for artifact A against a different artifact B) SHALL
  fail `artifact_digest` **and** `report_data` (the digest chains), with `ok is False`.
- A tampered `report_data` field in the evidence (artifact unchanged) SHALL fail `report_data` while
  `artifact_digest` still passes.
- A `quote_report_data` that does not match SHALL fail `quote_binding` while the offline chain checks
  still pass.

## Out of scope

- `digest`/`canonical_json` internals (`transcript`) and any actual TEE quote generation/parsing.
- The choice of which fields are run-identifying (the `_INPUT_FIELDS` membership is pinned, not
  re-justified).

## Verification

- `tests/test_spec_075_attestation.py` exercises each EARS block above using the **real** `digest`
  (so the binding, determinism, and tamper-detection are genuinely tested), pinning `inputs`-field
  restriction, the non-dict-`inputs` warning via `caplog`, the non-dict-`evidence` shape, the
  offline vs quote paths, and each failure-localization case. Digest equality assertions are stable
  across platforms because `digest` is deterministic.
