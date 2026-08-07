> ⛔ **Target the `test` branch, not `main`.** PRs into `main` from anywhere but `test` are auto-rejected.

> **Protected change route.** Changes outside `agent/**`, `agent.py`, and companion tests require
> an open linked issue carrying `benchmark-change-approved` before review.

## Summary

<!-- What does this change do, and why? -->

## Related issue

<!-- e.g. Fixes #123 -->
<!-- For any protected or mixed-surface change, the open issue above must already carry benchmark-change-approved. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / capability
- [ ] Benchmark / scoring change
- [ ] Docs / tooling
- [ ] Refactor (no behavior change)

## Area

- [ ] `agent/` (the maintainer agent)
- [ ] companion `tests/` for an agent change
- [ ] `benchmark/` (evaluation harness)
- [ ] packaging / CI
- [ ] docs

## How was this verified?

<!-- Commands you ran and what you observed. -->

## Checklist

- [ ] `ruff check .` passes
- [ ] `VANGUARSTEW_OFFLINE=1 python -m pytest -q` passes
- [ ] Added/updated tests for the change
- [ ] Updated docs (README / ROADMAP / CHANGELOG) if needed
- [ ] My changed-file set is in the component surface, or the linked open issue was approved before this PR
- [ ] No secrets, tokens, or private data included
