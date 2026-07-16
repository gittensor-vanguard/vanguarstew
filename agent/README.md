# `agent/` — the vanguarstew maintainer agent

This package is the scored surface. The benchmark freezes a repository at time *T*, hands the
agent only what was knowable then, asks it to plan and decide the next maintainer actions, and
scores those against what the real maintainer actually did in the revealed window *T→T+n*. Miners
edit this package; the `solve` entrypoint's signature must stay intact.

## The `solve` pipeline

`agent.py::solve` runs the maintainer workflow in order (see `agent.py`):

1. **`load_context(repo_path)`** (`agent/context.py`) — assemble the frozen, knowable-at-*T*
   context (below).
2. **`infer_philosophy(context, llm)`** (`agent/philosophy.py`) — read the repo's direction and
   conventions from that context, so later steps stay consistent with how *this* repo is run.
3. **`plan_next_actions(context, philosophy, n, llm)`** (`agent/planner.py`) — plan the next `n`
   maintainer actions/PRs in priority order, reconciled against the open-PR queue.
4. **`decide(context, philosophy, request, llm)`** (`agent/decider.py`) — turn the request into
   one concrete call (action, labels, reviewer, version bump, patch, rationale).

`solve` returns `{philosophy, plan, action, labels, reviewer, version_bump, patch, rationale, …}`.
`agent/llm.py` is a plain OpenAI-compatible client the benchmark builds from the run's
`--model/--api-base/--api-key`; `agent/review.py` powers the standalone `scripts/review_pr.py` CLI
and is not on the `solve` path.

## The context dict

`load_context` returns the GitHub-derived context that `benchmark/freeze.py` wrote at *T* —
returned **as written**, never re-derived — with these keys:

| key | shape | meaning |
| --- | --- | --- |
| `frozen_at` | `{commit, date}` | the freeze point |
| `recent_commits` | `[{sha, date, subject}]` | **newest-first** history at *T* (the git-only fallback omits `date`) |
| `open_issues`, `open_prs` | `[…]` | the backlog and review queue at *T* |
| `releases` | `[{tag}]` | tags merged at *T* (no dates) |
| `milestones`, `labels` | `[…]` | project metadata |
| `readme_excerpt` | `str` | leading README text |

### `repo_layout` — derived, not read

`load_context` additionally attaches **`repo_layout`**: the repository's real top-level entries at
*T* (directories carry a trailing `/`, so a plan can tell `docs/` from a top-level `NEWS` file).

The one contract worth stating plainly: **`repo_layout` is always derived from the frozen
checkout, never read from the context file.** `benchmark/freeze.py` never emits a `repo_layout`
key, so a value present in the JSON could only come from a hand-authored or tampered artifact —
and must not be able to feed invented paths into the plan. `repo_layout()` reads the tree exported
at *T* (`benchmark/freeze.py::export_tree`), so it is leakage-safe by construction, excludes the
freeze artifact and `.git`, sorts for a deterministic prompt, and caps at `REPO_LAYOUT_LIMIT`. A
missing, non-directory, or unreadable checkout degrades to `[]` ("layout unknown") rather than
raising — the planner then simply omits the layout note. Derivation runs on **both** the
frozen-file and git-fallback paths (`_with_repo_layout` / `load_context`).

## Plan-item `kind` vocabulary

Each plan item carries a `kind` (`agent/planner.py::_PLAN_KINDS`). Unknown values normalize to
`triage`:

```
feature  bugfix  refactor  docs  release  dep        # original maintainer actions
build    ci      test      perf  style    revert     # added to match the anchor (#1687)
triage                                                # a maintainer action, not a commit kind
```

**Every kind except `triage` maps onto a commit kind the objective anchor scores**
(`benchmark/score.py::_PLAN_KIND`). This alignment is load-bearing: `kind_recall` compares
`plan_kind(item["kind"])` against `commit_kind(revealed_subject)`, so a kind the anchor scores but
a plan cannot name would be structurally unscoreable — which is exactly why `build`/`ci`/`test`/
`perf`/`style`/`revert` were added. `triage` deliberately maps to nothing: it denotes reviewing or
scheduling, not a commit the revealed window would contain. `_CC_TYPE_TO_PLAN_KIND` mirrors the
same set on the read side, so `_recent_kinds_note` can report the repo's real recent kind mix.

`agent/` must not import `benchmark/` (a miner-only split is planned), so the two vocabularies are
kept aligned by convention rather than by a shared import, and locked by
`tests/test_planner.py::test_every_plan_kind_names_a_kind_the_objective_anchor_scores`.
