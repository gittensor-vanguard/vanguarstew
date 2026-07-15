# `agent/` — the maintainer agent

The scored, miner-editable surface. `agent.py::solve` at the repo root is the fixed entrypoint
the benchmark calls with a frozen checkout and a managed-inference endpoint; it runs the
maintainer workflow in order:

1. `context.load_context` — everything knowable at the freeze commit T.
2. `philosophy.infer_philosophy` — the repo's implicit direction (grounding; not scored directly).
3. `planner.plan_next_actions` — the next N maintainer actions/PRs.
   `decider.decide` — the concrete call for the request.

## The context dict

`load_context` returns the GitHub-derived content of the frozen context file — `frozen_at`,
`recent_commits` (`{sha, date, subject}`, no file paths), `open_issues`, `open_prs`, `labels`,
`milestones`, `releases`, `readme_excerpt` — **plus `repo_layout`**.

`repo_layout` is the frozen checkout's real top-level entries (`context.repo_layout`). It is
always *derived from the tree at T* on every load, never read from the context file: the freeze
never writes the key, so a value found in the JSON could only come from a hand-authored or
tampered artifact. It is leakage-safe (the tree as it stood at T) and it is what lets a plan
item's `files` name paths the repository actually has, rather than a conventional source layout
it may not — see `planner._repo_layout_note`.

## Plan-item `kind`

`planner._PLAN_KINDS` is the vocabulary a plan item's `kind` may use:

> `feature`, `bugfix`, `refactor`, `docs`, `release`, `dep`, `build`, `ci`, `test`, `perf`,
> `style`, `revert`, and `triage`

Every entry except `triage` maps onto a normalized commit kind the objective anchor scores
(`benchmark/score.py::_PLAN_KIND`), so a plan can name any kind the anchor reads out of real
commit subjects. `triage` is a maintainer action rather than a commit kind, maps to nothing
there, and is the fallback `planner._normalize_plan_item` coerces an unrecognized `kind` to.

`planner._CC_TYPE_TO_PLAN_KIND` maps Conventional-Commit types on *observed* subjects into that
same vocabulary. It mirrors the anchor's classifier in simplified form and is deliberately not
imported from `benchmark/` (`agent/` must not depend on it — a miner-only split is planned), so
the two must be kept aligned by hand; `tests/test_planner.py` pins the invariant.
