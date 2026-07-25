# Attested evaluation image publishing

The `Publish attested eval image` workflow builds the exact runtime defined by
`docker/eval.Dockerfile`. Pull requests only build and audit the image locally. A merge to `test`
that changes the measured runtime publishes one `linux/amd64` image to:

```text
ghcr.io/gittensor-vanguard/vanguarstew-eval:git-<full-commit-sha>
```

The workflow does not publish `latest` or another moving tag. If the commit tag already exists, a
rerun verifies its repository and revision labels, then reads its existing digest instead of
overwriting it. The Actions job summary reports the digest-qualified reference that must be
supplied to Polaris:

```text
ghcr.io/gittensor-vanguard/vanguarstew-eval@sha256:<manifest-digest>
```

## First publication

GitHub creates a new organization container package as private by default. After the first workflow
run publishes `vanguarstew-eval`, an organization owner must follow
[GitHub's package visibility instructions](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#configuring-visibility-of-packages-for-an-organization)
and change its visibility to **Public**, then rerun the failed publish job. GitHub documents this
visibility change as irreversible. The workflow deliberately fails its anonymous-pull check until
the image is public, because Polaris cannot use a registry image that requires the repository's
credentials.

After that one-time change, future immutable versions remain anonymously pullable. Copy only the
digest-qualified reference from the successful workflow summary into an attestation request; do not
use the commit tag as the verifier's expected image identity.
