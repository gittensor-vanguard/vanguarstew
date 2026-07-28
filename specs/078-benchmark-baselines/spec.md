# Spec 078 — reference baseline maintainers

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1971
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/baselines.py`](../../benchmark/baselines.py) (the module this spec
  binds), [`benchmark/runner.py`](../../benchmark/runner.py) (resolves `get_baseline`, calls
  the opponent as `opponent(dest, request, context=ctx, n=horizon)`, and keeps
  `baseline_solve = empty_solve` as a back-compat alias), [`benchmark/score.py`](../../benchmark/score.py)
  (`commit_kind` / `is_release_subject`, the canonical helpers baseline kind inference defers
  to), [`specs/001-solve-contract`](../001-solve-contract/spec.md) (the challenger-side output
  shape every baseline mirrors), [`specs/007-agent-planner`](../007-agent-planner/spec.md) (the
  plan-item kind vocabulary the baselines emit into)

This spec makes the **existing, implicit** baseline contract explicit. It describes the
as-built behavior of `benchmark/baselines.py`; it introduces **no behavior change**. Spec 001
pins the *challenger's* solve shape and Spec 007 pins the *planner's* kind vocabulary — neither
documents the opponents themselves: the registry, the empty floor, the kind-inference rules,
and the per-baseline plan ordering that the pairwise judge measures every challenger against.

## Why

The pairwise judge only means something relative to an opponent, so the four baselines are the
comparison anchor for the entire benchmark — "beating the baseline" is defined by exactly what
`empty`, `heuristic`, `queue_first`, and `stability_first` propose for a given frozen context.
They are deliberately deterministic and LLM-free (same context in, same plan out), which is
what makes a tally comparable run-to-run and challenger-to-challenger. A silent change to a
keyword bucket, a stability rank, or a rationale template moves the anchor and quietly rescores
every comparison, past and future, without a single challenger changing. Several of the
module's docstrings also describe intent that diverges from the as-built behavior in ways a
reviewer would want pinned down rather than re-discovered by reading the source.

## User stories

1. **As a benchmark operator**, I can work out by hand the exact plan a named opponent
   produces for a frozen context, so a tally shift between runs is attributable to the
   challenger or the task set — never to a drifting anchor.
2. **As a reviewer**, the registry, the solve-call shape the runner relies on, the
   kind-inference precedence, and each baseline's plan ordering are written down, so a
   baselines change is checked against intent instead of re-derived from code.
3. **As a challenger author**, I know what floor (`empty`) and what stronger bars
   (`heuristic` / `queue_first` / `stability_first`) my agent is judged against, including how
   malformed frozen-context entries are absorbed rather than crashing the opponent.

## Constants

- `BASELINES` SHALL register exactly the names `empty`, `heuristic`, `queue_first`,
  `stability_first`; `DEFAULT_BASELINE` SHALL be `"empty"`.
- Every baseline solve SHALL have the signature
  `(repo_path=None, request="", context=None, n=5, **_kw)`.
- `heuristic_philosophy` SHALL cap `values` at the top **3** inferred kinds and `evidence` at
  the first **5** commit subjects.
- `_STABILITY_KIND_RANK` SHALL be exactly
  `{bugfix: 0, refactor: 0, release: 1, feature: 2, docs: 2, dep: 2, triage: 3}`; any kind
  absent from the table ranks 3.
- `_ALLOWED` SHALL be exactly `{feature, bugfix, refactor, docs, release, dep, triage}` — the
  planner's kind vocabulary (Spec 007).

## Acceptance criteria (EARS)

### Registry (`BASELINES`, `DEFAULT_BASELINE`, `get_baseline`)

- `get_baseline(name)` SHALL return the registered callable for a known `name`.
- WHEN `name` is an unknown but hashable value THEN `get_baseline` SHALL raise `ValueError`
  with message `"unknown baseline {name!r}; choose from {sorted(BASELINES)}"`, chaining from
  the underlying `KeyError` with `from None` (no `__cause__`, context suppressed).
- **As-built divergence:** WHEN `name` is unhashable (e.g. a `list`) THEN the dict lookup
  itself raises `TypeError` — this propagates unchanged; only a lookup *miss* is translated to
  `ValueError`.

### Solve-call shape (all four baselines)

- Every baseline SHALL accept the runner's call form — `repo_path` and `request` positional,
  `context` and `n` keyword — and SHALL tolerate arbitrary extra keyword arguments via
  `**_kw`, so extending the runner's call shape cannot break an opponent.
- Every solve output SHALL be a dict with exactly the keys `{philosophy, plan, action,
  rationale}` and `action == "plan"`, matching the challenger's solve shape (Spec 001) so it
  flows through `_submission` unchanged.
- For `heuristic_solve`, `queue_first_solve`, and `stability_first_solve`: WHEN `context is
  not None` — including a falsy `{}` — THEN that context SHALL be used as-is;
  `load_context(repo_path)` SHALL be consulted only when `context is None`.
- **As-built divergence:** `empty_solve` ignores its `context` argument entirely — it never
  reads it and never calls `load_context`, even when `context is None`.

### The `empty` floor

- `empty_solve` SHALL return exactly
  `{"plan": [], "philosophy": {}, "action": "plan", "rationale": "baseline"}`, a fresh dict on
  every call, invariant to every argument it is given.

### Kind inference (`_infer_kind`, `_COMMIT_KIND_TO_BASELINE`, `_KIND_KEYWORDS`)

- `_infer_kind(text)` SHALL classify in this fixed precedence: (1) `score.is_release_subject`
  → `release`; (2) a Conventional-Commit kind from `score.commit_kind`, mapped through
  `_COMMIT_KIND_TO_BASELINE`; (3) the keyword pass over `_KIND_KEYWORDS`; (4) `triage`.
  Release detection is never re-implemented locally — it always defers to
  `score.is_release_subject` so baseline classification cannot drift from scoring semantics.
- `_COMMIT_KIND_TO_BASELINE` SHALL map every normalized `commit_kind` value onto the planner
  vocabulary: `feat→feature`, `fix→bugfix`, `docs→docs`, `refactor→refactor`, `perf→refactor`,
  `release→release`, `chore→dep`, `ci→refactor`, `test→refactor`, `build→refactor`,
  `style→refactor`, `revert→bugfix`.
- The keyword pass SHALL test case-insensitive substring needles in fixed first-match-wins
  bucket order `dep, docs, bugfix, refactor, feature, test` (so `"bump the guide"` classifies
  `dep`, not `docs`; `"fix the guide"` classifies `docs`, not `bugfix`); the `test` bucket
  SHALL resolve to `refactor` (the planner has no `test` kind), and any bucket result outside
  `_ALLOWED` SHALL resolve to `triage`.
- WHEN nothing matches THEN `_infer_kind` SHALL return `triage`.

### Context coercion (`_issue_title`, `_pr_title`, `_commit_subject`, `_baseline_list`, `_safe_backlog`)

- `_issue_title` / `_pr_title` SHALL return the stripped title only when the entry is a dict
  whose `title` is a string; every other shape yields `""`.
- `_commit_subject` SHALL return the subject only when the entry is a dict whose `subject` is
  a string. **As-built divergence from its own docstring:** a non-dict entry does not vanish —
  it is logged and yields `""`, but that `""` still flows into `heuristic_philosophy`'s
  `evidence` list as a placeholder **and** into the kind tally, where `_infer_kind("")`
  resolves to `triage` and can shift the dominant kind. The docstring's "logged and skipped"
  undersells the effect: the entry is skipped as a *subject*, not as a *vote*.
- `_baseline_list` SHALL return a real `list` unchanged (same object identity), treat `None`
  as `[]` silently, and treat any other type — including a `tuple` — as `[]` with a warning.
- `_safe_backlog` SHALL return `[]` for a non-dict context, and fail closed (`[]`) when
  `context["_issues_truncated"] is True` exactly (an identity check, not truthiness — a
  truthy non-`True` value does not disarm the backlog). `recent_commits` is read through
  `_baseline_list` directly and is **not** gated by `_issues_truncated`, so a truncated
  context still contributes commit-derived philosophy evidence and momentum items even while
  its issue/PR backlog reads empty.

### Heuristic philosophy (`heuristic_philosophy`)

- The output SHALL be a dict with exactly `{summary, values, merge_bar, direction, evidence}`.
- `dominant` SHALL be the most common kind inferred over `recent_commits`; ties SHALL resolve
  to whichever kind was **seen first** (`Counter.most_common` preserves insertion order on
  ties); an empty commit history SHALL yield `dominant == "triage"` and `values == ["triage"]`.
- `summary` SHALL be `"Recent activity is dominated by {dominant} work; {n} open issue(s)
  await triage."` and `direction` SHALL be `"continue {dominant}-oriented work and clear the
  issue backlog"`, where `n` is `len` of the truncation-gated `open_issues` list — including
  untitled/malformed entries, which `heuristic_plan` skips but this count does not.
- `merge_bar` SHALL always be the fixed string `"inferred from recent commit patterns (no
  explicit signal)"`.
- WHEN the context is not a dict THEN the whole output SHALL equal the empty-context output
  (the function coerces `context = {}` up front).

### Heuristic plan (`heuristic_plan`)

- Items SHALL appear in this fixed section order, before any `[:n]` cap is applied: (1) one
  `"Address issue: {title}"` item per **titled** open issue, in backlog order, `kind =
  _infer_kind(title)`, theme `"issue backlog"`; (2) one `"Continue {kind} work"` item per
  distinct inferred commit kind in descending frequency (ties first-seen), theme
  `"{kind} momentum"`, rationale ending in `"({count} recent)"`; (3) one extra
  `"Prepare the next release"` item (kind `release`, theme `"release cadence"`) appended WHEN
  any recent commit infers `release` — additional to, not a replacement for, a `"Continue
  release work"` momentum item that section (2) may already have produced.
- Every item SHALL carry exactly `{title, kind, rationale, theme}`.
- The result SHALL be `items[:n]` — a plain slice over the section order above, so a low `n`
  drops later sections first; `n <= 0` SHALL yield `[]`.

### Queue-first (`_review_queue_items`, `queue_first_plan`, `queue_first_solve`)

- Each **titled** open PR, in queue order, SHALL become one item `"Review and merge PR:
  {title}"` (kind `triage`, theme `"PR review queue"`), with a trailing `" (#{number})"` iff
  `number` is an `int` and not a `bool`; any other `number` type SHALL be omitted entirely,
  never rendered as text.
- WHEN `limit is None` THEN the queue SHALL be exhausted uncapped. **As-built divergence from
  its own docstring:** the cap comparison (`len(items) >= limit`) runs *after* the item for
  the current PR is appended, so `limit <= 0` still yields exactly the first titled item
  rather than the documented empty result — `_review_queue_items(ctx, 0)` returns one item,
  not zero. The caller's own `[:n]` slice is what keeps `queue_first_plan(ctx, 0) == []`.
- `queue_first_plan` SHALL return `reviews[:n]` when the queue alone reaches `n` items, else
  `reviews + heuristic_plan(context, n - len(reviews))`. WHEN the queue is empty THEN the
  result SHALL equal `heuristic_plan(context, n)` exactly — queue-first is never a weaker
  opponent than heuristic for lack of a queue, matching the module docstring's plan/philosophy
  claim.
- `queue_first_solve`'s `rationale` SHALL be `"queue-first baseline: clear {N} open PR(s) in
  the review queue, then continue the dominant recent themes"`, where `N` counts **all**
  titled PRs in the truncation-gated backlog — not the `n`-capped review-item count used to
  build `plan`. **As-built divergence:** with an empty queue, `plan` and `philosophy` match
  `heuristic` exactly (per the module docstring), but the `rationale` string does not — it
  still reads `"clear 0 open PR(s)..."` rather than the heuristic wrapper's own rationale.

### Stability-first (`stability_first_plan`, `_stability_rank`)

- `stability_first_plan(context, n)` SHALL be a stable sort of `heuristic_plan(context, n)`
  keyed by `_stability_rank(item["kind"])` (unknown kinds rank 3, same as `triage`) — the same
  item multiset as the heuristic plan, reordered only.
- The `n`-cap SHALL apply to the heuristic plan **before** the stability reorder: a
  high-priority item that the heuristic `[:n]` cap already dropped is not resurrected by
  sorting, so `stability_first_plan` can under-represent `bugfix`/`refactor` relative to an
  uncapped stability sort of the full candidate set.

### Solve wrappers (`heuristic_solve`, `queue_first_solve`, `stability_first_solve`)

- All three SHALL call `heuristic_philosophy(ctx)` for their `philosophy` field — the same
  dict shape and content regardless of which baseline is selected — and differ only in `plan`
  and `rationale`.
- `heuristic_solve`'s `rationale` SHALL be `"heuristic baseline: extrapolate the dominant
  recent themes and address {n} open issue(s)"`; `stability_first_solve`'s SHALL be
  `"stability-first baseline: stabilize before greenfield across {n} open issue(s) and
  recent-theme momentum"`; both `n` values are the truncation-gated `open_issues` list length,
  same source as `heuristic_philosophy`'s count.

## Out of scope

- The judge, `_submission`, and the runner's tally logic (`benchmark/runner.py`); the
  challenger's own solve contract (Spec 001) and the planner's kind semantics (Spec 007).
- `score.commit_kind` / `score.is_release_subject` internals — this spec pins only how their
  outputs map onto the baseline vocabulary, not their own classification rules.
- Adding, removing, or re-tuning any baseline, keyword bucket, stability rank, or rationale
  template — this spec documents current behavior and introduces none of its own.

## Verification

- `tests/test_spec_078_baselines.py` exercises each EARS block above against small synthetic
  contexts, pinning exact literal dicts, lists, and strings rather than re-deriving expected
  values from the module under test: the exact registry and unknown-name error text (plus the
  unhashable-name `TypeError` passthrough), the runner call shape and both context branches,
  the four solve signatures, the `empty_solve` literal, the full Conventional-Commit mapping
  table, keyword-bucket order and substring semantics, the exact `_ALLOWED` vocabulary, the
  full philosophy dict (tie-break, malformed-entry triage vote and `""` evidence placeholder,
  evidence cap, list-length issue count), the ordered heuristic plan and its plain-slice cap,
  review-item shape and the post-append `limit<=0` quirk, queue-fill-vs-fallthrough
  composition and the uncapped rationale count, the literal stability rank table, and
  cap-before-reorder.
- `tests/test_baselines.py` keeps the adjacent regression coverage this spec does not
  duplicate: registry identity, the truncation fail-closed matrix, release-detection parity
  with scoring, malformed-container tolerance, and end-to-end `run_replay` baseline selection.
