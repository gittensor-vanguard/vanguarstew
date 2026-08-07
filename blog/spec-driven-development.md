# vanguarstew adopts spec-driven development

*July 6, 2026*

vanguarstew — the maintainer-intelligence component benchmarked against real GitHub
history — is adopting **spec-driven development (SDD)** as its methodology. Here's
what that means, why we're doing it, and how it maps to a project whose benchmark
was already spec-driven by construction.

## The spec is the source of truth

SDD inverts the traditional relationship between requirements and code. The spec
— a structured, version-controlled document with unambiguous acceptance criteria
— is the primary artifact. Code is the build output. When requirements change,
the spec is edited first and the relevant code is regenerated.

This isn't a theoretical preference. It solves three failure modes that became
acute once LLM-based coding agents entered the workflow:

1. **Intent drift** — "Add login" is wildly underspecified. The model picks
   reasonable defaults that rarely match what the team wanted.
2. **Context decay** — As codebases grow past the agent's effective context
   window, it forgets earlier decisions and silently contradicts them.
3. **Unverifiable output** — Without explicit acceptance criteria, there's no
   way to determine whether generated code is correct.

A precise spec fixes all three by acting as the layer between human intent and
machine execution.

## The 4-phase loop

```
Specify (what/why) → Plan (how) → Tasks (order) → Implement (go)
     ↑                                              |
     └────────── spec evolves, regenerates ──────────┘
```

Every phase boundary has a human checkpoint. This is what makes SDD predictable:
the spec is reviewed before the plan; the plan before tasks; tasks before
implementation. No phase is skipped.

## The constitution

We've added `AGENTS.md` at the repo root — a project constitution written in
**EARS** (Easy Approach to Requirements Syntax) notation. It contains durable
project-wide rules that every agent, operator, and CI check operates under:

- **Agent contract**: `solve()` is the single entrypoint. Offline stubs.
  Managed-inference parameters.
- **Benchmark integrity**: non-string fields are coerced, not crashed on.
  Forward-looking signals are stripped. Held-out repos score separately.
- **Code quality**: 75% coverage floor. Tests required with code changes.
  Ruff and pytest must pass.
- **Factory authority**: roles are least-privilege, private review stays
  role-scoped, and owner effects require external approval.

These aren't new rules — they're existing CI and convention written as
unambiguous statements an agent can parse and act on.

## The benchmark was always a spec

vanguarstew's evaluation pipeline maps onto SDD naturally:

| SDD concept | vanguarstew |
|---|---|
| Spec | Revealed git history — actual maintainer decisions |
| Plan | Agent's `philosophy → plan → decide` workflow |
| Tasks | Per-PR decisions (merge, labels, next-work) |
| Verification | Objective anchor scores against history |

`taskgen.py` generates replay tasks from git history — the revealed trajectory
**is** the specification. `score.py` checks whether the agent's output matches
that spec. This is SDD by construction — we're now making it explicit.

## What changes for operators

The active constitution now defines component, benchmark, factory-authority,
and runtime boundaries. The OpenVang factory does not turn a change request
into an owner action; external approval remains mandatory.

## What changes for agent development

New agent features and benchmark changes will be specified before they're
implemented. A `specs/` directory will hold one directory per feature:

```
specs/001-solve-contract/
  spec.md     — user stories + EARS criteria + out-of-scope
  plan.md     — architecture, data model, contracts
  tasks.md    — atomic, independently shippable checklist
```

The first formal spec will be the `solve()` output contract — the exact fields,
types, and validation rules the maintainer component must satisfy. This is the
interface between agent and benchmark, and having it as an EARS spec keeps the
component boundary unambiguous.

## What's next

M4 hardening is active — 10 open PRs fixing the crash-and-correctness gap that
blocks the M3 generalization acceptance run. Once those land and the benchmark
completes a clean multi-repo replay against the curated repo set, the M3
acceptance signal (`generalization_gap`) will be documented.

The next platform milestone is the OpenVang factory: role-scoped scheduler,
build/QA, and read-only subnet adapters before any separately approved owner-action gateway.

---

*[AGENTS.md](/AGENTS.md) — project constitution*
*[Spec-driven development](/docs/spec-driven-development.md) — methodology doc*
