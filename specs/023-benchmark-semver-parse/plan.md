# Plan 023 — semver parsing and bump classification

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #854

Maps the [spec](./spec.md) onto `benchmark/score.py::parse_semver` and `bump_level` as-built.
No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_023_semver_parse.py` |
| ------------ | --------------------------------------------- |
| `parse_semver` input guard | `test_parse_semver_non_string_returns_none` |
| `parse_semver` token extraction | `test_parse_semver_leading_v`, `test_parse_semver_missing_patch`, `test_parse_semver_ignores_prerelease_suffix`, `test_parse_semver_no_token_returns_none`, `test_parse_semver_first_token_wins` |
| `parse_semver` output shape | `test_parse_semver_returns_int_tuple`, `test_parse_semver_does_not_mutate_input` |
| `bump_level` input guard | `test_bump_level_non_tuple_returns_none`, `test_bump_level_short_tuple_returns_none`, `test_bump_level_empty_tuple_returns_none` |
| `bump_level` forward bump only | `test_bump_level_no_change_returns_none`, `test_bump_level_backward_returns_none` |
| `bump_level` classification | `test_bump_level_major_minor_patch`, `test_bump_level_returns_canonical_levels_only` |
| Pure evaluation | covered by unit imports (no I/O) |

## Verification strategy

One contract-test group per EARS section; integration tests stay in `tests/test_score.py`.
