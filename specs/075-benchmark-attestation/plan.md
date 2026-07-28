# Plan 075 — attestation evidence binding

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1967

Maps the [spec](./spec.md) onto `benchmark/attestation.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_075_attestation.py` |
| ------------ | -------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| `build_evidence` | `test_evidence_shape_and_version`, `test_inputs_restricted_to_known_fields`, `test_absent_input_field_is_none`, `test_non_dict_inputs_warns_and_binds_empty`, `test_artifact_and_report_digests_match_primitive`, `test_build_evidence_is_deterministic`, `test_report_data_changes_with_inputs_and_artifact` |
| `verify_evidence` | `test_non_dict_evidence_shape`, `test_roundtrip_ok`, `test_quote_match_passes_binding`, `test_quote_absent_is_skipped_not_failed`, `test_detail_all_passed_and_failed` |
| Failure localization | `test_edited_artifact_fails_both_digests`, `test_tampered_report_data_fails_only_report_data`, `test_quote_mismatch_fails_only_quote_binding` |

## Verification strategy

One contract-test group per EARS section, exercised through the **real** `benchmark.transcript.digest`
(never mocked) so the cryptographic binding, its determinism, and tamper-detection are genuinely
tested rather than asserted against a stub. Following the lessons from prior spec-PR closures, every
edge is pinned: the `inputs` field restriction (unknown keys dropped, absent fields `None`), the
non-dict-`inputs` warning via `caplog`, the special non-dict-`evidence` return shape (no
`quote_checked`/`expected_report_data`), the offline (`quote_report_data is None`) path being skipped
not failed, and each failure-localization case (edited artifact fails both digest checks; a tampered
`report_data` fails only that check; a quote mismatch fails only `quote_binding`). Digest-equality
assertions are stable across platforms because `digest` is deterministic. Values are literal;
digests are compared by recomputation, not hardcoded hashes.
