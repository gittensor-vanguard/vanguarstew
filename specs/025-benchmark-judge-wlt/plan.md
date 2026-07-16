# Plan 025 — judge W-L-T summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #873

Maps the [spec](./spec.md) onto `benchmark/judge_wlt.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_025_judge_wlt.py` |
| ------------ | ------------------------------------------ |
| Input guard | `test_non_dict_artifact_*` |
| W-L-T extraction | `test_reads_valid_wlt_*`, `test_malformed_judge_report_*`, `test_negative_and_float_counts_rejected` |
| Zero total | `test_zero_total_is_zero_not_none` |
| Artifact kind | `test_kind_from_artifact_kind` |
| Headline — unavailable | `test_headline_unavailable_*` |
| Headline — happy path | `test_headline_happy_path` |
| Pure evaluation | `test_does_not_mutate_artifact`, `test_no_io_imports` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in `tests/test_judge_wlt.py`.
