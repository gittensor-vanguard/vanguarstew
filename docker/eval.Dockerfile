# Reproducible evaluation image -- the unit a TEE attests.
#
#   docker build -f docker/eval.Dockerfile -t vanguarstew-eval .
#   docker inspect --format '{{index .RepoDigests 0}}' vanguarstew-eval   # <- the measured identity
#
# The image DIGEST is the thing an attestation quote binds to: a verifier checks that the digest
# claimed in the quote is the digest of this published, open-source image, which is what makes
# "unmodified code ran" checkable rather than asserted.
#
# This project is unusually well-suited to that: pyproject.toml declares `dependencies = []` -- the
# whole eval runs on the Python standard library, so there is no dependency resolution to pin, and
# no wheel-build nondeterminism to chase. Base image + git + this source tree is the entire TCB.
#
# The base is pinned BY DIGEST, not by tag: `python:3.12-slim` is re-pushed regularly, and a tag
# that moves underneath you silently changes the image measurement an attestation quote commits to
# -- the one thing that must not drift. Refresh deliberately (docker pull, re-read RepoDigests)
# rather than letting upstream do it for you.
#
# Still to tighten for production attestation: pin the apt package versions, or move to a
# distroless base with git vendored in, so `apt-get install` cannot pull a different git between
# builds. Left as-is here because it does not affect reproducibility of a single built image --
# the digest of THIS image is what gets attested.

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

# git is a genuine runtime dependency: the benchmark materializes and freezes real repositories.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Repos arrive mounted or unpacked from outside the image, so their ownership never matches the
# container user and git's "dubious ownership" guard aborts every rev-list. That guard protects a
# multi-user machine from a hostile repo owner; neither condition holds in a single-purpose eval
# sandbox that only ever reads repositories it was explicitly handed, and inside an enclave the
# input set is fixed by the attested measurement anyway.
RUN git config --global --add safe.directory '*'

# Deterministic interpreter behaviour: no .pyc writes, unbuffered output, and a fixed hash seed so
# any incidental set/dict iteration in the pipeline cannot vary between runs of the same image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0

WORKDIR /eval
COPY . /eval

# Offline by default: the image is built to replay a recorded transcript, not to make live model
# calls. A record-mode run overrides this and points --api-base at the proxy instead.
ENV VANGUARSTEW_OFFLINE=1

# No ENTRYPOINT on purpose -- the same image serves the three roles the spike needs:
#   replay a run:  python -m scripts.transcript_proxy --mode replay --transcript t.json
#   score a run:   python -m scripts.run_eval --repo ... --api-base http://127.0.0.1:8712/v1
#   verify a run:  python -m scripts.verify_attestation --artifact a.json --evidence e.json
CMD ["python", "-m", "scripts.verify_attestation", "--help"]
