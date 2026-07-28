# Spec 076 — Leaderboard ranking contract

**Module:** `benchmark/leaderboard.py`
**Status:** Accepted (characterization)
**Tests:** `tests/test_spec_076_leaderboard.py`
**Issue:** #1941

## Purpose

The benchmark's ultimate question is *which candidate wins*. `compare_eval` diffs two artifacts
and `trend` tracks one score over successive runs; `leaderboard` is the third N-way operation:
given several replay artifacts evaluated on the same benchmark (one per candidate agent, or one
per configuration), rank them by their headline composite score and show how far each trails the
best — reproducibly, instead of eyeballed across files.

This spec pins the ranking, tie-handling, component breakdown, and malformed-input degradation of
`rank`, `leaderboard_headline`, and the helpers behind them, so a change to the "pick the best"
view is a deliberate, reviewed change rather than a silent one.

## Definitions

- **Headline score.** Each entry's single comparable score is extracted with
  `benchmark.trend.headline_score`, so the leaderboard stays consistent with the trend view. Its
  contract (pinned here because the leaderboard depends on it):
  - a plain single/multi-repo artifact's headline is its **top-level** `composite_mean`;
  - a `--generalization` artifact (both `tuned` and `held_out` present as dicts) scores on its
    **`tuned`** `composite_mean` — the primary figure;
  - an aggregate that scored no repos (`scored_repos: 0`) carries a placeholder `composite_mean`
    of `0.0` and is treated as **unscored** (`None`);
  - a non-dict artifact, or anything without a finite numeric score, yields `None`.
- **Scored / unscored.** An entry with a non-`None` headline score is *scored* and appears in
  `ranking`; an entry whose score is `None` is *unscored*, listed by label in `unscored`, and
  **never ranked** — a partial or malformed entry can neither silently win nor crash the board.
- **Competition ranking.** Equal scores share a rank and the next rank skips accordingly
  (`1, 2, 2, 4`). Ties keep input order.
- **Numeric.** `_is_number` accepts only a **finite, non-boolean** `int`/`float`. `NaN`,
  `Infinity`, `bool`, and an oversized int that overflows `float()` (e.g. `10**400`) are all
  non-numeric and degrade the affected value to `None`.
- **Components / M7 foresight.** Each scored row also carries the judge/objective component means
  and the four M7 foresight axes (`module_recall_mean`, `kind_recall_mean`, `release_accuracy`,
  `bump_accuracy`) read from the headline partition — the legible axes behind `objective_mean`.
  Each is rounded to 3 places, or `None` when the axis had no applicable tasks or the artifact
  predates the foresight breakdown.

## Acceptance criteria (EARS)

- **AC-1 — Rank best first.** When given `(label, artifact)` entries with usable scores, `rank`
  SHALL return `ranking` ordered highest score first, each row carrying `rank`, `label`,
  `composite_mean`, and `delta_from_best` (`composite_mean - best`, `0.0` for the leader and
  negative for the rest).
- **AC-2 — Competition ties.** When two or more entries share a score, `rank` SHALL assign them
  the same `rank` and skip the following rank(s) (`1, 2, 2, 4`), preserving input order among the
  tied entries.
- **AC-3 — Best summary.** `rank` SHALL report `best` as `{label, composite_mean}` of the top
  scored entry, or `None` when nothing scored.
- **AC-4 — Unscored partition.** When an entry has no usable headline score, `rank` SHALL place
  its label in `unscored`, exclude it from `ranking`, and count it in `total` but not `scored`.
- **AC-5 — Generalization headline.** When an artifact carries both `tuned` and `held_out` dict
  partitions, `rank` SHALL score and break down that entry on its `tuned` partition.
- **AC-6 — Zero-scored aggregate.** When an aggregate artifact reports `scored_repos: 0`, `rank`
  SHALL treat it as unscored regardless of its placeholder `composite_mean`.
- **AC-7 — Component breakdown.** Each scored row SHALL expose `judge_mean`, `objective_mean`,
  and the four foresight axes, each rounded to 3 places, with any missing/malformed/non-finite
  value rendered as `None` rather than an `inf`/`nan` or a crash.
- **AC-8 — Malformed container.** When `entries` is a non-`None`, non-list value, `rank` SHALL
  emit a `logging.WARNING` naming the offending type and treat it as no candidates.
- **AC-9 — Malformed entry.** When an individual entry is not a length-2 `(label, artifact)`
  pair, `rank` SHALL emit a `logging.WARNING` naming the offending index/type and skip it,
  ranking the remaining well-formed entries.
- **AC-10 — Headline string.** `leaderboard_headline` SHALL name the leader and its score, count
  the other scored entries (`over N other(s)`) and any `unscored` tail, and return
  `"leaderboard: no scored artifacts"` for an empty, all-unscored, or non-dict summary.

## Non-goals

- No I/O: `leaderboard` never reads or writes files and never mutates its inputs.
- It does not define `headline_score`, `composite_mean`, or the foresight axes themselves — it
  consumes them. Their computation is owned by `benchmark/trend.py` and the scoring modules.
