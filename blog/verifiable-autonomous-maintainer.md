# Autonomy is not enough. A maintainer agent should be verifiable.

*July 28, 2026*

Software agents can open pull requests, review diffs, and press a merge button. That is useful—but
it is not enough to make them trustworthy maintainers.

A maintainer operates where mistakes compound. One weak review can merge a regression. One noisy
metric can reward the wrong contribution. One unavailable dependency can leave a queue in an
ambiguous state. If an autonomous system cannot show what it measured, constrain what it executed,
and stop safely when verification fails, then autonomy only makes uncertainty move faster.

With **[v0.8.0](https://github.com/gittensor-vanguard/vanguarstew/releases/tag/v0.8.0)**,
Vanguarstew takes a large step beyond measuring maintainer-agent performance. It now connects that
benchmark to a live, autonomous, fail-closed maintenance pipeline with a receipt-bound integrity
layer.

The important change is not that the agent can act on its own. The important change is that a
score-backed action has to survive a chain of measurable and verifiable gates first.

---

## From a benchmark to an operating system for maintenance

Vanguarstew began with a hard question: can an agent predict what experienced maintainers will do
next?

The benchmark answers that by freezing real repositories in the past, asking the agent to infer
their maintainer philosophy and next development priorities, and comparing those predictions with
the future that actually happened. The answer key is real project history—not a synthetic list of
ideal responses.

That makes maintainer judgment measurable. But a benchmark alone does not answer the operational
question:

**Can the same system review live contributions reliably enough to participate in maintaining its
own repository?**

Version 0.8.0 connects those two sides. Eligible incoming changes move through four stages:

1. **Measure** — generate before-and-after benchmark evidence and validate its structure.
2. **Isolate** — run candidate-controlled code in a restricted, non-root, read-only environment
   without network access or model credentials.
3. **Recompute** — send the exact bounded artifacts to a measured Polaris Intel TDX workload, where
   a fixed validator recomputes the gates, score delta, and final conservative decision with
   `egress=none`.
4. **Act** — accept the score-backed result only after exact receipt-binding verification. If any
   required stage fails, the pipeline takes no score-backed action.

This is the difference between automation and accountable automation. The pipeline does not merely
report that evaluation happened. It requires evidence tied to the workload, inputs, and output that
produced the decision.

---

## Why this is a big update

### 1. Performance and operation are now connected

Many agent projects stop at an offline score. The benchmark says the model performed well, but the
production workflow remains a separate collection of scripts and assumptions.

Vanguarstew now uses its measurement system as part of its maintenance loop. The same ideas that
evaluate maintainer judgment—frozen evidence, reproducible gates, conservative decisions, and
explicit failure states—also govern whether an eligible contribution can receive a score-backed
outcome.

The benchmark is no longer only a report card. It is part of the operating discipline.

### 2. Candidate code does not inherit reviewer trust

A contribution being evaluated must not receive the credentials or ambient authority of the
system evaluating it.

Candidate execution is therefore separated from the trusted orchestration layer. It runs without
network access, with read-only inputs, as an unprivileged user, and without access to the model
credential. A narrowly scoped broker mediates the model interface while keeping the credential
outside candidate-controlled code.

This does not make arbitrary code harmless. It creates a concrete, testable boundary that sharply
reduces what evaluated code can reach and makes failures easier to contain.

### 3. The final decision is recomputed, not merely notarized

Hashing a host-produced verdict inside a TEE would prove that the TEE saw the verdict. It would not
prove that the decision itself followed the benchmark contract.

Vanguarstew's receipt workload instead receives the bounded benchmark artifacts and runs a fixed
validator inside the measured environment. That validator repeats the integrity gates, recomputes
the score deltas, applies the conservative combination rule, and emits only the canonical aggregate
result.

The local verifier then checks freshness, workload binding, mounted-input binding, exact output,
no-egress policy, and the receipt's report-data binding before the result becomes usable.

The receipt is therefore attached to decision recomputation—not just to a string containing a
decision.

### 4. Failure has a safe meaning

Reliable autonomy is defined as much by what happens when a dependency fails as by what happens on
the happy path.

If isolation cannot start, evidence is incomplete, a gate is inconsistent, the execution service
is unavailable, the cost policy is not satisfied, or receipt verification fails, the benchmark
result is unavailable. The pipeline does not silently downgrade to an unverified score.

That fail-closed rule is essential. A trust boundary that disappears during an outage is not a
trust boundary.

---

## What remains under human control

Autonomy should have a defined authority boundary.

Changes to the benchmark and contribution-integrity system can alter how future contributions are
measured. Those changes remain subject to manual maintainer review. Contributor-authored benchmark
changes must begin with an open issue, discussion with the maintainers, and the public
`benchmark-change-approved` label before a pull request is opened.

This is deliberate. The system may use the benchmark to assess changes, but it must not be able to
rewrite its own scoring rules and approve that rewrite through the same automated path.

---

## The honest trust boundary

The language around trusted execution is easy to overstate, so the boundary matters:

- The current result is **`polaris-verified`**. Vanguarstew independently recomputes the receipt
  bindings, but it does not claim independent Intel-chain verification without a separately
  reviewed local DCAP/QVL policy.
- Hosted model inference happens **outside** the TEE. The measured workload verifies and recomputes
  the benchmark decision from the bound artifacts; it does not prove that model inference ran
  inside confidential hardware.
- This is an **execution-integrity** layer, not a workload-confidentiality claim.
- This release does not claim GPU provenance.
- Sensitive execution artifacts are retained under restricted handling rather than published as
  part of routine review output.

These limits do not weaken the update. They make it useful. Trust grows when a system says exactly
what its evidence proves—and exactly what it does not.

---

## What contributors should expect

Vanguarstew can now participate as an active maintainer rather than only as a benchmarked agent.
Eligible pull requests may be reviewed, scored, labeled, merged, or closed through the autonomous
pipeline, while protected benchmark and integrity changes remain manually controlled.

The system is live, but it is still early. A working pipeline is not the same thing as an
ecosystem-proven pipeline. Real contributions will surface edge cases that controlled validation
cannot predict.

If an outcome is delayed, unclear, or unexpected, contact the maintainers or open an issue. Those
reports are not interruptions to the project—they are how a reliable maintainer is built.

---

## The larger goal

We are not trying to build a bot that produces the most activity. We are trying to build a
maintainer agent whose judgment improves, whose actions are constrained, and whose important
decisions can be checked.

That requires three things working together:

- a benchmark grounded in real maintainer history;
- an autonomous system capable of acting on live repository work; and
- an integrity layer that turns critical execution claims into verifiable evidence.

Version 0.8.0 brings those pieces together for the first time in Vanguarstew.

Autonomy is the visible part. Accountability is the important part.

**[Read the v0.8.0 release notes →](https://github.com/gittensor-vanguard/vanguarstew/releases/tag/v0.8.0)**
