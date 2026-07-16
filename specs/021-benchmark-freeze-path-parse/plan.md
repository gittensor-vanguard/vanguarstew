# Plan 021 — NUL-delimited git path parsing

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #838

Maps the [spec](./spec.md) onto `benchmark/freeze.py::parse_path_list` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_021_freeze_path_parse.py` |
| ------------ | --------------------------------------------------- |
| Input type | `test_empty_string_returns_empty_list` |
| NUL splitting | `test_splits_on_nul_not_whitespace` |
| Empty-field dropping | `test_drops_empty_fields` |
| Output shape | `test_output_is_list_of_non_empty_strings`, `test_does_not_mutate_input` |
| Pure evaluation | covered by unit tests (no I/O imports) |

## Verification strategy

One contract-test group per EARS section; integration tests stay elsewhere.
