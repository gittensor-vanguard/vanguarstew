# Plan 024 — maintainer kind normalization

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #855

Maps the [spec](./spec.md) onto `benchmark/score.py::commit_kind` and `plan_kind` as-built.
No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_024_commit_kind.py` |
| ------------ | --------------------------------------------- |
| `commit_kind` input guard | `test_commit_kind_non_string_returns_none` |
| `commit_kind` CC prefix | `test_commit_kind_maps_conventional_prefixes`, `test_commit_kind_normalizes_synonyms` |
| `commit_kind` release subjects | `test_commit_kind_release_cuts`, `test_commit_kind_non_release_scoped_stays_non_release` |
| `commit_kind` unclassified | `test_commit_kind_unclassified_subjects_return_none` |
| `plan_kind` input guard | `test_plan_kind_non_string_returns_none` |
| `plan_kind` normalization | `test_plan_kind_strips_whitespace_and_case` |
| `plan_kind` vocabulary | `test_plan_kind_maps_aliases`, `test_plan_kind_triage_and_unknown_return_none` |
| Vocabulary symmetry | `test_plan_and_commit_kind_vocabularies_stay_symmetric` |
| Pure evaluation | covered by unit imports (no I/O) |

## Verification strategy

One contract-test group per EARS section; integration tests stay in `tests/test_score.py`.
