# Plan 012 — benchmark trend headline score

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #761

How the [spec](./spec.md) maps onto `benchmark/trend.py::headline_score` as-built. No new product
code; this records the contract surface so future headline changes are reviewed against a plan.

## Architecture

```
headline_score(artifact)
  ├─ reject non-dict → None
  ├─ pick source: tuned dict when tuned+held_out are dicts, else artifact
  ├─ unscored aggregate: scored_repos is numeric 0 → None
  └─ composite_mean numeric → round(float, 3); else None
```

## Contract surface (functions this spec pins)

`headline_score` only. Related helpers (`trend`, `trend_headline`, `_trend_series`) are out of
scope for this spec.

## The invariants this pins

- **One number:** every gate that calls `headline_score` agrees on the comparable score.
- **Fail closed on placeholders:** `scored_repos: 0` never yields a numeric headline.
- **Generalization primary:** tuned partition is the headline source, not held-out.

## Verification strategy

`tests/test_spec_012_headline.py` (this PR) exercises each EARS row directly; `tests/test_trend.py`
covers the wider trend pipeline.

## Out of scope for this plan

Changing headline extraction, trend regression math, or artifact schema.
