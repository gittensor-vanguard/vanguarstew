# Spec 053 — freeze digest summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1162
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (repo identity),
  [`benchmark/freeze_coverage.py`](../../benchmark/freeze_coverage.py) (freeze coverage),
  [`specs/032-benchmark-freeze-coverage/spec.md`](../032-benchmark-freeze-coverage/spec.md) (freeze coverage contract)

This spec makes the **existing, implicit** freeze-digest contract explicit. It describes the
as-built behavior of `benchmark/freeze_digest.py`; it introduces **no behavior change**.

## Why

`comparability` checks whether two artifacts name the same repos; `freeze_digest` captures repo
identities and freeze commits from a single artifact as a sorted, JSON-friendly fingerprint for
logging or cache keys.

## User stories

1. **As a benchmark operator**, I can read a stable freeze digest from a replay artifact.
2. **As a CI maintainer**, I can log a stable `freeze_digest_headline()` string alongside the JSON
   digest.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `freeze_digest(artifact)` SHALL treat it as `{}`
  and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Repo identity (`_repo_key`)

- SHALL return the first non-empty string among `repo_path`, `url`, `repo`, `name`, `repo_name`.
- WHEN no name key is present THEN it SHALL use the first ten characters of `freeze_commit` when
  that value is a non-empty string.
- OTHERWISE it SHALL return `repr(sorted(entry.keys()))`.

### Freeze commit (`_freeze_commit`)

- SHALL return `freeze_commit` when it is a non-empty string; OTHERWISE `None`.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]`.
- WHEN `per_repo` is not a `list` THEN it SHALL log a warning and return `[]`.
- Non-`dict` list entries SHALL be logged and skipped.

### Row collection (`_collect_rows`)

- **`generalization`** — SHALL collect rows from `tuned.per_repo` and `held_out.per_repo`, tagging
  each entry with its partition name.
- **`multi`** — SHALL collect rows from top-level `per_repo` with partition `"multi"`.
- **Other kinds** — SHALL return an empty list.

### Freeze digest (`freeze_digest`)

Every digest SHALL include: `kind`, `entries`, `count`.

- Each entry SHALL include `partition`, `repo`, and `freeze_commit`.
- `entries` SHALL be sorted by `(partition, repo, freeze_commit or "")`.
- `count` SHALL be `len(entries)`.

### Freeze digest headline

- `count_txt` SHALL be `str(count)` when `count` is a non-boolean `int`, otherwise `n/a`.
- The headline SHALL use `entry` when `count == 1`, otherwise `entries`.
- The headline SHALL be:
  `freeze digest: {kind} with {count_txt} entr{y|ies}`.

### Pure evaluation

- The module SHALL perform no I/O.
- `freeze_digest()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_053_freeze_digest.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_freeze_digest.py`.
