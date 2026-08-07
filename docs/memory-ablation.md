# Memory ablation protocol

This local-only protocol measures whether time-safe memory helps the maintainer agent on the same
historical tasks. It is deliberately stricter than comparing two unrelated benchmark averages.

## What is compared

`scripts.run_memory_ablation` runs each freeze task twice, with identical repository, task
selection, seed, model settings, and scoring settings:

1. baseline: no `memory_view`;
2. treatment: a public-only, benchmark-mode `memory_view`.

The order is counterbalanced per task: half the tasks run baseline first and half run memory
first. This prevents a changing model endpoint or warm cache from being mistaken for memory value.

The treatment corpus is source-anchored. It contains only bounded public first-parent commit
metadata — subject, normalized action class, and changed paths — with each source commit's
original SHA and timestamp. The importer is deterministic, reads no diff body or author identity,
and creates an isolated store for the run. Every item is filtered again at the task
freeze time. Retrieval is gated by repository-specific terms from frozen recent history; no
lexical support means an empty memory view rather than a broad historical fallback. This is a
reproducible retrieval ablation, not a claim that a controller had written a contemporaneous
private memory record.

The agent receives recalled text as labeled evidence only. It never receives a store path,
credentials, mutation API, source corpus, or a future-facing view. Results retain only the
existing digest-only memory commitment.

## Predeclared success gate

The command reports `significant_improvement: true` only when all of these are true:

- at least six exactly matched freeze tasks;
- mean paired objective improvement is at least `0.05`;
- the deterministic 95% bootstrap lower bound is greater than zero; and
- a two-sided exact sign test on non-tied objective deltas has `p < 0.05`.

The report also contains paired composite deltas, per-agent invocation latency, and whole-run
operational time. Setup/cache time is reported separately and never treated as a memory latency
win. A fast result with no quality improvement is not a success; neither is a larger score from
unmatched tasks.

## Coverage gate before model calls

Run `scripts.run_memory_coverage` first for every repository in
`benchmark/memory_quality_protocol.json`. It measures only whether recalled past source-path
metadata overlaps later changed modules, using the future window exclusively as evaluator ground
truth. The report contains aggregate counts and a memory commitment, never module/path lists or
raw recalled text. A weak coverage report means do not spend model budget on that memory policy.

## Local use

Clone a public repository locally, then run the two arms with a pinned model or recorded replay
endpoint. The API key is read from the named local environment variable and is never printed.

```bash
set -a && . /path/to/.env && set +a
python -m scripts.run_memory_ablation \
  --repo /path/to/public/repo \
  --memory-repository-id github.com/owner/repo \
  --tasks 6 --horizon 5 \
--model <pinned-model> --api-base <openai-compatible-endpoint> \
  --api-key-env DEEPSEEK_API --env-file /path/to/.env \
  --out /tmp/memory-ablation.json
```

For a formal, externally repeatable claim, pin or replay the model transcript and run enough
predeclared task/repository pairs. A live-model pilot is useful for product iteration but does not
by itself establish repeatable model behavior or TEE attestation.

## Boundaries

This protocol never accepts source text generated after a freeze point, backdated controller
opinions, participant acceptance history, or coordination data. It must remain local unless a
separate publication review confirms that the output contains only allowed aggregate commitments.
