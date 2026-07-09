# Spec-driven development for vanguarstew

vanguarstew adopts spec-driven development (SDD): the spec is the source of truth,
code is the build output. When requirements change, the spec is edited first.

## Why

The benchmark IS a spec — `taskgen.py` generates replay tasks from git history;
the revealed trajectory provides the acceptance criteria. `score.py` checks agent
output against that spec. This is SDD by construction. Making it explicit:

- **Prevents intent drift**: a precise spec beats a vague prompt.
- **Prevents context decay**: the spec is versioned with the code.
- **Makes output verifiable**: EARS criteria produce unambiguous pass/fail checks.

## The 4-phase loop

```
Specify (what/why) → Plan (how) → Tasks (order) → Implement (go)
     ↑                                              |
     └────────── spec evolves, regenerates ──────────┘
```

Human review at every phase boundary. No skipping.

## Project constitution

`AGENTS.md` at the repo root contains durable project-wide rules written in
EARS notation. Every agent, contributor, and CI check operates under these rules.
The constitution is the immutable backdrop — specifications inherit it.

## EARS notation

Acceptance criteria use EARS (Easy Approach to Requirements Syntax):

| Pattern | Template | Example |
|---|---|---|
| Ubiquitous | The system shall [behavior] | The system shall reject PRs that lower coverage |
| Event-driven | WHEN [trigger] THE system SHALL [response] | WHEN a contributor opens a PR against main THEN CI SHALL auto-close |
| State-driven | WHILE [state] THE system SHALL [behavior] | WHILE a contributor has >2 open PRs THEN CI SHALL block new PRs |
| Unwanted | IF [condition] THEN THE system SHALL [response] | IF the LLM emits a non-string field THEN the pipeline SHALL coerce and warn |
| Optional | WHERE [feature] THE system SHALL [behavior] | WHERE `--generalization` is set THEN held-out repos SHALL score separately |

## Feature specs

For new agent features and benchmark changes, specs live in `specs/NNN-feature-name/`:

```
specs/001-solve-contract/
  spec.md     — user stories + EARS criteria + out-of-scope
  plan.md     — architecture, data model, contracts
  tasks.md    — atomic, independently shippable checklist
```

One feature = one spec directory. Specs cite the constitution; code cites the spec.

## What the benchmark already specifies

The benchmark pipeline is an implicit SDD system:

| SDD concept | vanguarstew equivalent |
|---|---|
| Spec (acceptance criteria) | Revealed git history — actual maintainer decisions |
| Plan | Agent's philosophy → plan → decide workflow |
| Tasks | Decomposed per-PR decisions (merge, labels, next-work) |
| Verification | Objective anchor scores against history |

The M5 `solve()` contract spec will make this explicit for subnet miners.
