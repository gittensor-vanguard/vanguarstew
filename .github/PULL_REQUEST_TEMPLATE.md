> ⛔ **Target the `test` branch, not `main`.** PRs into `main` from anywhere but `test` are auto-rejected — see [CONTRIBUTING → Branches](../CONTRIBUTING.md#branches).

## Summary

<!-- What does this change do, and why? -->

## Related issue

<!-- e.g. Fixes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature / capability
- [ ] Benchmark / scoring change
- [ ] Docs / tooling
- [ ] Refactor (no behavior change)

## Area

- [ ] `agent/` (the maintainer agent)
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
- [ ] No secrets, tokens, or private data included
