# Attested evaluation image validation

The `Validate attested eval image` workflow builds and audits `docker/eval.Dockerfile` on pull
requests to `test`. It does not log in to a registry, publish an image, change package visibility,
or run after merge.

The image and the `/v1/attest` adapter remain a separate path for deliberately public one-shot
benchmark proofs. They are not the deployment surface for a persistent private workload. The
existing `ghcr.io/gittensor-vanguard/vanguarstew-eval` package must remain private unless a future
public-proof proposal receives its own review and explicit approval.

Persistent sealed workloads use Polaris's `/api/v2/sandbox` surface and the network-free planner
documented in [Polaris sealed sandbox](polaris-sealed-sandbox.md). That path omits the image field
and transfers workload code over the owner-controlled SSH channel.
