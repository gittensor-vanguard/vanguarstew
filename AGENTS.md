# OpenVang project constitution

Durable project-wide rules for the OpenVang agent factory and the Vanguarstew
maintainer-intelligence component. Code, tests, and automation must follow
these rules.

## Component contract

- The maintainer component shall expose `solve(repo_path, request, ...)` as its
  stable entrypoint.
- Managed inference parameters are supplied by the controller; agent code shall
  not discover or substitute credentials.
- `VANGUARSTEW_OFFLINE=1` shall select the deterministic offline stub.
- Benchmark and live persistent memory shall remain time-safe, controller-owned,
  and read-only from the maintainer component.

## Benchmark and execution integrity

- Forward-looking signal shall not cross a benchmark freeze boundary.
- Held-out repositories shall be evaluated separately from tuned repositories.
- Public artifacts and TEE evidence shall contain only receipt-safe commitments,
  never raw private memory, review material, credentials, or private sources.
- Polaris integration shall be described as execution integrity, not workload
  confidentiality.

## Factory authority

- Every factory worker shall declare one role contract from `openvang/factory.py`.
- No role may automatically access a wallet, submit an on-chain transaction,
  change emissions, vote in governance, mutate GitHub, or publish.
- Owner-level effects require a separate external approval and signing boundary;
  a factory `ActionIntent` is non-executable by design.
- Role-private memory, including private maintainer-review material, shall never
  cross role boundaries or enter public, benchmark, or TEE artifacts.
- Security QA is defensive and isolated; it may propose containment but may not
  perform an offensive or production mutation.

## Quality gates

- Changes under `agent/`, `benchmark/`, `openvang/`, or `vanguarstew_runtime/`
  shall include matching tests.
- `ruff check .` and the relevant offline test suite shall pass before release.
- Runtime defaults shall remain dry-run, loopback-only, private, and without a
  GitHub write path.
