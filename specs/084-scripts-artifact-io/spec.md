# Spec 084 — Shared artifact-loader CLI error contract

**Module:** `scripts/artifact_io.py`
**Status:** Accepted (characterization)
**Tests:** `tests/test_spec_084_artifact_io.py`
**Issue:** #2001 (resolves the "raw traceback" family: #612, #604, #641, #608, #554, #687, #1048, #1906, #1958)

## Purpose

`load_artifact` is the single source of the path-error taxonomy every artifact-consuming gate CLI
relies on (`scripts/report.py`, `trend.py`, `regression.py`, the `*_integrity` / `*_gate` /
`*_share` CLIs, …). It was extracted (#1938) so those CLIs stop pasting near-copies that exited
`1` on a path failure — colliding with the gating `1` used by `--strict` — and misreported
dangling symlinks and symlink loops.

The contract is load-bearing: a regression re-introduces raw tracebacks or the exit-code
collision. This spec pins the exit code, the per-class messages, and the ordering constraints so
the shared loader's behaviour is reviewed rather than implicit.

## Definitions

- **Artifact.** A UTF-8 JSON file whose root is a JSON **object** (`dict`). The consumers index
  it by key, so a valid array/scalar root is still rejected.
- **Load failure.** Any condition that prevents returning such an object: a bad path, an
  unreadable file, non-UTF-8 bytes, invalid JSON, or a non-object root.
- **Gating exit vs load exit.** Consumer CLIs use exit **1** for a gating verdict (`--strict` /
  `--fail-on-regression` fired). `load_artifact` uses exit **2** for every load failure, so the
  two are always distinguishable.

## Acceptance criteria (EARS)

- **AC-1 — Success.** When `path` is a readable UTF-8 JSON file with an object root,
  `load_artifact` SHALL return the parsed `dict` and SHALL NOT exit.
- **AC-2 — Always exit 2 on failure.** For every load-failure class, `load_artifact` SHALL raise
  `SystemExit` with code **2** (never 1), and SHALL write a message to `stderr` (never a raw
  traceback).
- **AC-3 — Missing file.** When `path` does not exist, the message SHALL be `artifact not found:
  <path>`.
- **AC-4 — Broken symlink.** When `path` is a symlink whose target does not exist, the message
  SHALL distinguish it: `artifact is a broken symlink (target does not exist): <path>` — not
  "not found".
- **AC-5 — Directory.** When `path` is a directory, the message SHALL say so (`artifact path is a
  directory, not a file:` on POSIX; on Windows it surfaces via `PermissionError` as `artifact is
  not readable …`).
- **AC-6 — Parent not a directory.** When a parent component of `path` is a file, the message
  SHALL be `artifact path is not a file (a parent component is not a directory): <path>`.
- **AC-7 — Symlink loop.** When resolving `path` raises `OSError(ELOOP)`, the message SHALL be
  `artifact path is a symlink loop: <path>` — not "not found".
- **AC-8 — Invalid JSON.** When the bytes are UTF-8 but not valid JSON (including an oversized
  integer literal that raises a plain `ValueError` on py3.11+), the message SHALL start with
  `artifact is not valid JSON (`.
- **AC-9 — Non-UTF-8.** When the bytes are not valid UTF-8, the message SHALL start with
  `artifact is not valid UTF-8 JSON (` — reported *before* the invalid-JSON arm, since
  `UnicodeDecodeError` subclasses `ValueError`.
- **AC-10 — Non-object root.** When the JSON root is not an object, the message SHALL be
  `artifact must be a JSON object: <path>`.
- **AC-11 — No TOCTOU pre-check.** Broken-symlink classification SHALL run *after* `open` fails
  (via `FileNotFoundError` + `os.path.islink`), so there is no `exists()`/`open()` pre-check that
  could itself raise on a symlink loop or race with the open.

## Non-goals

- It does not parse CLI arguments, render reports, or decide gating verdicts — it only turns a
  path into a validated artifact object or a clean exit. The consumer CLIs own their `argparse`
  and their exit-1 gating.
