"""Record and replay the LLM calls a benchmark run makes, so a run becomes reproducible.

Why this exists (TEE track, Phase 0): every other input to a replay run is already pinned — the
repo is frozen at commit T, the task RNG is seeded, the judge's dual-order rotation is seeded. The
ONE thing that is not reproducible is the model call itself. Two runs of identical inputs can
diverge purely because a hosted model answered differently the second time.

That matters beyond convenience. An attestation quote proves "this exact code ran unmodified and
produced this artifact" — but if the computation isn't reproducible, nobody can independently
re-derive the artifact to check it, and the attestation proves far less than it appears to. A
transcript makes the model an *input* to the run rather than a live dependency: record once, then
anyone can replay the same run offline and get byte-identical output.

Two properties this file is careful about:

  - **Ordered replay.** The same prompt can legitimately be asked more than once in a run (the
    dual-order judge asks about the same pair twice). Responses are therefore stored as an ordered
    list per key and served in recorded order, so replay reproduces the original *sequence*, not
    just the original set of answers.
  - **Byte-stable keys.** The key is a hash of the canonical form of the semantically-relevant
    request fields, so it does not shift because a dict happened to serialize in a different
    order, or because an unrelated transport field (stream, user, ...) was added.
"""

from __future__ import annotations

import hashlib
import json
import logging

logger = logging.getLogger(__name__)

TRANSCRIPT_VERSION = 1

# The request fields that change the *meaning* of a completion, and therefore belong in the key.
# Transport/bookkeeping fields (stream, user, n, ...) are deliberately excluded: they do not change
# which answer is correct to replay, and including them would make a transcript brittle to caller
# refactors that don't affect the model's task.
_KEYED_REQUEST_FIELDS = ("model", "messages", "temperature")


def canonical_json(value) -> str:
    """A byte-stable JSON serialization: sorted keys, no incidental whitespace, ASCII-escaped.

    Every determinism guarantee here rests on this being stable across machines, Python versions,
    and dict insertion order — so it is used for BOTH the transcript keys and the artifact digest
    that gets bound into an attestation quote.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=str)


def digest(value) -> str:
    """``sha256`` of :func:`canonical_json` — the primitive behind transcript keys and the
    artifact digest bound into an attestation quote's ``report_data``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def request_key(request) -> str:
    """The replay key for a chat-completion request.

    Built only from :data:`_KEYED_REQUEST_FIELDS`, so it is stable against unrelated transport
    fields. A non-dict request (malformed caller, truncated proxy read) is keyed on its canonical
    form rather than raising — an unmatchable key simply misses on replay, which the caller
    already has to handle, and that is a better failure than taking the run down.
    """
    if not isinstance(request, dict):
        logger.warning("transcript: request is %s, not a dict; keying verbatim",
                       type(request).__name__)
        return digest(request)
    return digest({field: request.get(field) for field in _KEYED_REQUEST_FIELDS})


class TranscriptStore:
    """An ordered record of the (request -> response) pairs one run made.

    Record mode collects them; replay mode serves them back in the order they were recorded,
    matched by :func:`request_key`.
    """

    def __init__(self, entries=None):
        self._entries = list(entries or [])
        self._cursor = {}

    # -- recording -------------------------------------------------------------------------

    def record(self, request, response: str) -> None:
        """Append one completed call. ``response`` is the raw assistant message content."""
        self._entries.append({
            "key": request_key(request),
            "request": request if isinstance(request, dict) else None,
            "response": response,
        })

    # -- replay ----------------------------------------------------------------------------

    def replay(self, request):
        """The next recorded response for ``request``, or ``None`` when the transcript has none.

        ``None`` (rather than an exception) is the miss signal because a miss is a *data* problem
        the caller must decide about: a proxy returns an error to the agent, while a verifier
        wants to report "this transcript does not cover the run" rather than crash mid-check.

        Repeated identical requests are served in recorded order via a per-key cursor, so a run
        that asks the same question twice replays both original answers, in sequence.
        """
        key = request_key(request)
        matches = [entry for entry in self._entries if entry.get("key") == key]
        if not matches:
            return None
        index = self._cursor.get(key, 0)
        if index >= len(matches):
            # More calls than were recorded: the replayed run diverged from the recorded one.
            # Loud, because it means the transcript no longer describes this run.
            logger.warning("transcript: exhausted %d recorded response(s) for key %s",
                           len(matches), key[:12])
            return None
        self._cursor[key] = index + 1
        return matches[index].get("response")

    def reset(self) -> None:
        """Rewind replay cursors so the same store can drive another run from the start."""
        self._cursor = {}

    # -- persistence -----------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def to_dict(self) -> dict:
        return {"version": TRANSCRIPT_VERSION, "entries": self._entries}

    @classmethod
    def from_dict(cls, data) -> "TranscriptStore":
        """Rebuild from :meth:`to_dict` output, tolerating a malformed/partial file.

        A transcript is an untrusted artifact — it may be hand-edited, truncated by an interrupted
        write, or produced by a newer version. Non-list ``entries`` and non-dict rows are dropped
        with a warning rather than raising, matching this repo's coerce-or-default posture for
        frozen inputs.
        """
        if not isinstance(data, dict):
            logger.warning("transcript: file is %s, not a dict; treating as empty",
                           type(data).__name__)
            return cls()
        entries = data.get("entries")
        if not isinstance(entries, list):
            if entries is not None:
                logger.warning("transcript: entries is %s, not a list; treating as empty",
                               type(entries).__name__)
            return cls()
        return cls([entry for entry in entries if isinstance(entry, dict)])

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=1, sort_keys=True)

    @classmethod
    def load(cls, path: str) -> "TranscriptStore":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def digest(self) -> str:
        """A stable hash of the recorded calls — the transcript's identity.

        Only the keys and responses are hashed, not the stored request bodies: the bodies are kept
        for auditability (a verifier can recompute a key from one and confirm it matches), but they
        are derived data, and hashing them would make the digest shift on a purely cosmetic
        request-shape change that did not alter a single answer.
        """
        return digest([[entry.get("key"), entry.get("response")] for entry in self._entries])
