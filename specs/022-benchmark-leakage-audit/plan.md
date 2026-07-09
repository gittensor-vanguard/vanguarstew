# Plan 022 — frozen-context leakage audit

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #841

Maps the [spec](./spec.md) onto `benchmark/leakage_audit.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_022_leakage_audit.py` |
| ------------ | --------------------------------------------- |
| Audited fields | `test_audit_context_flags_scrubbable_fields`, `test_finding_shape` |
| Non-dict and malformed context handling | `test_non_dict_context_*`, `test_malformed_list_fields_*`, `test_skips_non_dict_rows_*` |
| Clean gate | `test_is_clean_*` |
| Scrub alignment | `test_scrubbed_context_audits_clean` |
| False-positive guard | `test_plain_numbers_not_flagged` |
| Findings-list sanitization | `test_findings_list_*` (includes logging contract) |
| Audit headline | `test_audit_headline_*` (includes non-list + logging) |
| Pure evaluation | `test_audit_context_does_not_mutate_context` |

## Verification strategy

Every EARS clause has at least one contract test, including logging assertions via `caplog`.
