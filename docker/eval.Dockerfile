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
# For production attestation, tighten two things beyond this file:
#   - pin the base image by digest (FROM python:3.12-slim@sha256:...), not by tag, so the
#     measurement cannot shift under you when the tag is re-pushed;
#   - pin the apt package versions, or drop to a distroless base with git vendored in.
# Both are deliberately left as tags here so the spike stays buildable as-is.

FROM python:3.12-slim

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
