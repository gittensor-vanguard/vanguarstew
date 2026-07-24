# Spec 078 — reference baseline maintainers

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1971
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/baselines.py`](../../benchmark/baselines.py) (the module this spec
  binds), [`benchmark/runner.py`](../../benchmark/runner.py) (consumes `get_baseline` and
  `empty_solve`, calls the opponent as `opponent(dest, request, context=ctx, n=horizon)`, and
  keeps the `baseline_solve = empty_solve` back-compat alias),
  [`specs/001-solve-contract`](../001-solve-contract/spec.md) (the challenger-side output-shape
  sibling every baseline mirrors), [`specs/007-agent-planner`](../007-agent-planner/spec.md)
  (the plan-item kind vocabulary the baselines emit into)

This spec makes the **existing, implicit** baseline contract explicit. It describes the
as-built behavior of `benchmark/baselines.py`; it introduces **no behavior change**. The
sibling specs cover adjacent concerns, not this one: 001 pins the *challenger's* solve output
shape, and 007 pins the *planner's* item vocabulary — nothing yet documents the opponents
themselves: the registry, the empty floor's exact shape, the kind-inference rules, and the
per-baseline plan ordering the pairwise judge compares every challenger against.

## Why

The pairwise judge only means something relative to an opponent, so the baselines are the
**fixed comparison anchor** of the whole benchmark: "beating the baseline" is defined by
exactly what `empty`, `heuristic`, `queue_first`, and `stability_first` propose for a frozen
context. They are deliberately LLM-free and deterministic — same context in, same plan out —
which is what makes tallies comparable run-to-run and challenger-to-challenger. A silent
change to a keyword table, a tier rank, or a rationale template moves the anchor and rescores
every past and future comparison without touching a single challenger. Writing the rules down
pins what the anchor *is*, so baseline edits are reviewed as scoring-semantics changes, and so
agent work can be checked against the invariant that it leaves the opponents untouched.

## User stories

1. **As a benchmark operator**, I can derive by hand the exact plan each named opponent
   produces for a frozen context, so a tally shift between runs is attributable to the
   challenger or the task set — never to a drifting anchor.
2. **As a reviewer**, the registry, the solve-call shape the runner relies on, the
   kind-inference precedence, and each baseline's ordering rules are written down, so a
   baselines change is checked against intent instead of re-derived from code.
3. **As a challenger author**, I know the floor (`empty`) and the stronger bars
   (`heuristic`/`queue_first`/`stability_first`) my agent's plan is judged against, including
   how malformed frozen-context entries are absorbed rather than crashing the opponent.

## Constants

- `BASELINES` SHALL map exactly the names `empty`, `heuristic`, `queue_first`, and
  `stability_first`; `DEFAULT_BASELINE` SHALL be `"empty"` (the `run_replay` and
  `scripts/run_eval.py --baseline` default).
- Every baseline solve SHALL have the signature
  `(repo_path=None, request="", context=None, n=5, **_kw)`.
- `heuristic_philosophy` SHALL surface the top **3** kinds as `values` and the first **5**
  commit subjects as `evidence`.
- `_STABILITY_KIND_RANK` SHALL be exactly `bugfix: 0, refactor: 0, release: 1, feature: 2,
  docs: 2, dep: 2, triage: 3`, with any unknown kind ranking 3.
- The plan-kind vocabulary `_ALLOWED` SHALL be exactly
  `{feature, bugfix, refactor, docs, release, dep, triage}` (the planner's kinds, Spec 007).

## Acceptance criteria (EARS)

### Registry (`BASELINES`, `DEFAULT_BASELINE`, `get_baseline`)

- `get_baseline(name)` SHALL resolve each registered name to its solve callable.
- WHEN `name` is an unknown hashable THEN `get_baseline` SHALL raise `ValueError` whose
  message names the offender (`repr` for a string) and lists the sorted valid choices, with
  the underlying `KeyError` chain suppressed. **As-built:** an *unhashable* name propagates
  `TypeError` instead — only the lookup miss is translated.

### Solve-call shape (all four baselines)

- Every baseline SHALL accept the runner's call form — `repo_path` and `request` positional,
  `context` and `n` keyword — and SHALL tolerate arbitrary extra keyword arguments (`**_kw`),
  so a runner-side call-shape extension cannot break an opponent.
- Every solve output SHALL be a dict with exactly the keys
  `{philosophy, plan, action, rationale}` and `action == "plan"` — the same judged surface as
  the challenger's solve (Spec 001), so it flows through `_submission` unchanged.
- WHEN `context is not None` — including a falsy `{}` — THEN it SHALL be used as-is;
  `load_context(repo_path)` is consulted **only** when `context is None`.

### The `empty` floor

- `empty_solve` SHALL return exactly
  `{"plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline"}` — a fresh dict
  per call, invariant to every argument.

### Kind inference (`_infer_kind`, `_COMMIT_KIND_TO_BASELINE`, `_KIND_KEYWORDS`)

- `_infer_kind` SHALL classify in fixed precedence: (1) `score.is_release_subject` →
  `release` (release detection defers to the canonical scoring helper, never a local
  needle); (2) a Conventional-Commit kind from `score.commit_kind`, mapped through
  `_COMMIT_KIND_TO_BASELINE`; (3) the keyword pass; (4) `triage`.
- `_COMMIT_KIND_TO_BASELINE` SHALL map every normalized commit kind onto the planner
  vocabulary: `feat → feature`, `fix → bugfix`, `docs → docs`, `refactor → refactor`,
  `perf → refactor`, `ci → refactor`, `test → refactor`, `build → refactor`,
  `style → refactor`, `chore → dep`, `revert → bugfix`, `release → release`.
- The keyword pass SHALL test case-insensitive **substring** needles in fixed first-match-wins
  bucket order `dep, docs, bugfix, refactor, feature, test` (so `"bump the guide"` is `dep`,
  not `docs`; `"fix the guide"` is `docs`, not `bugfix`), with the `test` bucket resolving to
  `refactor` (the planner has no `test` kind).
- WHEN the text is falsy (`""`, `None`) or matches nothing THEN the kind SHALL be `triage`.
  **As-built:** a *truthy non-string* raises `AttributeError` — callers coerce through
  `_commit_subject`/`_issue_title`/`_pr_title` first, so no context value reaches it.

### Context coercion (`_issue_title`, `_pr_title`, `_commit_subject`, `_baseline_list`, `_safe_backlog`)

- `_issue_title`/`_pr_title` SHALL return the stripped title only for a dict entry with a
  string title; every other shape yields `""`.
- `_commit_subject` SHALL return the subject only for a dict entry with a string subject; a
  non-dict entry yields `""` **with** a warning log, a dict with a non-string subject yields
  `""` without one.
- `_baseline_list` SHALL return a real `list` unchanged (same object), silently treat `None`
  as `[]`, and treat any other type — including a tuple — as `[]` with a warning (#515).
- `_safe_backlog` SHALL return `[]` for a non-dict context and fail closed when
  `_issues_truncated` is the literal `True` (identity check — a truthy non-bool does not
  disarm the queue, #722/#957); `recent_commits` is **not** gated by the flag, so a truncated
  context still yields philosophy evidence and momentum items.

### Heuristic philosophy (`heuristic_philosophy`)

- The output SHALL be a dict with exactly
  `{summary, values, merge_bar, direction, evidence}`: `summary` =
  `"Recent activity is dominated by {dominant} work; {n} open issue(s) await triage."`,
  `merge_bar` = `"inferred from recent commit patterns (no explicit signal)"`, `direction` =
  `"continue {dominant}-oriented work and clear the issue backlog"`.
- `dominant` SHALL be the most common inferred kind over `recent_commits`; WHEN counts tie
  THEN the kind **seen first** wins (`Counter.most_common` is a stable sort over insertion
  order); WHEN the history is empty THEN `dominant` is `triage` and `values` is
  `["triage"]`.
- The issue count SHALL be `len` of the truncation-gated `open_issues` **list** — malformed
  and titleless entries are counted here even though `heuristic_plan` skips them.
- `evidence` SHALL be the first 5 entries of `recent_commits` through `_commit_subject` —
  a malformed entry appears as `""` (a placeholder, not dropped) and is **counted as a
  `triage` vote** in the kind tally, which can shift `dominant`.
- WHEN the context is not a dict THEN the output SHALL equal the empty-context output.

### Heuristic plan (`heuristic_plan`)

- Items SHALL appear in fixed section order: (1) one
  `"Address issue: {title}"` item per **titled** open issue, in backlog order, with
  `kind = _infer_kind(title)`, theme `issue backlog`; (2) one `"Continue {kind} work"` item
  per inferred kind in frequency order (ties first-seen), theme `{kind} momentum`, rationale
  ending `"({count} recent)"`; (3) a single `"Prepare the next release"` item (kind
  `release`, theme `release cadence`) appended WHEN any recent commit infers `release` — *in
  addition to* the `Continue release work` momentum item.
- Every item SHALL carry exactly `{title, kind, rationale, theme}`.
- The result SHALL be capped as `items[:n]` — the cap truncates the section order above;
  `n=0` yields `[]`.

### Queue-first (`_review_queue_items`, `queue_first_plan`, `queue_first_solve`)

- Each **titled** open PR, in queue order, SHALL become one item
  `"Review and merge PR: {title}"` with kind `triage`, theme `PR review queue`, and a
  `" (#{number})"` suffix **iff** `number` is an `int` and not a `bool` — a string or
  boolean number is omitted, never rendered.
- WHEN `limit is None` THEN the queue SHALL NOT be capped. **As-built:** the cap check runs
  *after* an item is appended, so `limit <= 0` still yields the first titled item;
  `queue_first_plan`'s outer slice contains it, so `queue_first_plan(ctx, 0) == []` holds.
- `queue_first_plan` SHALL return `reviews[:n]` when the queue fills the horizon, else
  `reviews + heuristic_plan(context, n - len(reviews))`; WHEN the queue is empty THEN the
  plan SHALL equal `heuristic_plan(context, n)` exactly.
- `queue_first_solve`'s rationale SHALL be
  `"queue-first baseline: clear {N} open PR(s) in the review queue, then continue the
  dominant recent themes"` where `N` counts **all** titled PRs in the truncation-gated queue
  — not the `n`-capped review-item count.

### Stability-first (`stability_first_plan`, `_stability_rank`)

- `stability_first_plan(context, n)` SHALL be a **stable** sort of `heuristic_plan(context,
  n)` by `_STABILITY_KIND_RANK` over `item.get("kind", "triage")` — the same item multiset,
  with within-tier heuristic order preserved.
- The cap SHALL apply **before** the reorder: truncation follows *heuristic* order, so a
  high-priority momentum item the heuristic cap dropped is not resurrected by the sort.

### Solve wrappers (`heuristic_solve`, `queue_first_solve`, `stability_first_solve`)

- All three SHALL share the same `heuristic_philosophy(ctx)` and differ only in `plan` and
  `rationale`; the rationale templates SHALL be `"heuristic baseline: extrapolate the
  dominant recent themes and address {n} open issue(s)"` and `"stability-first baseline:
  stabilize before greenfield across {n} open issue(s) and recent-theme momentum"` (and the
  queue-first template above), where the issue count is the truncation-gated `open_issues`
  list length.

## Out of scope

- The judge, `_submission`, and the tally (runner-side); the challenger's own solve contract
  (Spec 001) and the planner's semantics (Spec 007).
- `score.commit_kind` / `score.is_release_subject` internals — this spec pins only the
  mapping of their outputs onto the baseline vocabulary.
- Adding, removing, or re-tuning any baseline, keyword, tier rank, or template.

## Verification

- `tests/test_spec_078_baselines.py` exercises each EARS block above with neutral synthetic
  contexts: the exact registry and error message, the runner call shape, both context
  branches (context-as-is, and `context=None` consulting `load_context`), the four solve
  signatures, the `empty_solve` literal, the Conventional-Commit mapping table (every row
  reachable through `_infer_kind` — the `release → release` row is shadowed by the
  `is_release_subject` check that fires first and is deliberately not pinned), the exact
  `_ALLOWED` vocabulary, keyword bucket order across its meaningful adjacencies and
  substring semantics, the exact philosophy dict (top-3 `values` cap, tie-break,
  malformed-entry triage votes and `""` evidence placeholders, evidence cap, list-length
  issue counts), the full ordered heuristic plan and its `[:n]` cap, the review-item shape
  and the post-append `limit=0` quirk, queue-fill vs fall-through composition, the full-queue
  rationale count, the literal stability rank table, and cap-before-reorder — all pinned as
  **literal** dicts, titles, and strings, never re-derived from the module.
- `tests/test_baselines.py` keeps the adjacent regressions: registry identity, the
  truncation fail-closed matrix (#722/#957), release-detection parity with scoring
  (#129), ci/test bucket mapping (#270), malformed-container tolerance (#515), the
  warning log a non-dict commit entry emits, and the end-to-end `run_replay` baseline
  selection; this file pins exact literals and ordering rather than presence, and
  overlaps those assertions only where an exact-literal pin subsumes a presence check.
