# Spec 084 — Plan

## Approach

`scripts/artifact_io.py` already ships and is imported by the artifact-consuming gate CLIs. This
spec is a **characterization** effort requested by issue #2001: document the existing shared-loader
contract and pin it with tests, adding no behaviour. Every asserted exit code and message prefix
in `tests/test_spec_084_artifact_io.py` was taken from the live loader against real filesystem
fixtures, not hand-written.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | success returns the dict | `test_loads_a_json_object_and_returns_it` |
| AC-2 | always exit 2 on failure | `test_every_failure_class_uses_exit_2_never_1` (+ every case below asserts code 2) |
| AC-3 | missing file | `test_missing_file` |
| AC-4 | broken symlink distinguished | `test_broken_symlink_is_distinguished_from_a_missing_file` |
| AC-5 | directory | `test_directory_path` |
| AC-6 | parent not a directory | `test_parent_component_is_not_a_directory` |
| AC-7 | symlink loop | `test_symlink_loop_is_not_reported_as_not_found` |
| AC-8 | invalid JSON (incl. oversized int) | `test_invalid_json`, `test_oversized_int_literal_is_a_clean_json_error_not_a_traceback` |
| AC-9 | non-UTF-8 before invalid-JSON | `test_non_utf8_is_distinguished_from_invalid_json` |
| AC-10 | non-object root | `test_non_object_root_is_rejected` |
| AC-11 | no TOCTOU pre-check | covered by AC-4 + AC-7 passing without an `exists()` probe raising |

## Issue coverage

Issue #2001 asks for the shared loader's contract to be written down. Its behaviour is the
resolution of a whole family of "raw traceback instead of a clean error" reports — #612, #604,
#641, #608, #554, #687, #1048 — plus the symlink-taxonomy reports #1906 / #1958. Pinning the
per-class message and the exit-2 guarantee locks that resolution so a regression re-trips a test.

## Risks

- **Platform-conditional directory arm.** On Windows a directory raises `PermissionError`, not
  `IsADirectoryError`; `test_directory_path` accepts either message so the suite is portable while
  still asserting a clean exit 2.
- **Exception ordering is load-bearing.** `UnicodeDecodeError` subclasses `ValueError`, so AC-9
  must be caught before AC-8; `test_non_utf8_is_distinguished_from_invalid_json` pins that order.
- **Real filesystem fixtures.** Symlink loops and broken symlinks are created on disk via
  `tmp_path`, so the tests exercise the actual `open`/`OSError` paths rather than mocks.

## Out of scope

No changes to `scripts/artifact_io.py` or any consumer CLI. Documentation and tests only.
