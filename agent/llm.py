"""OpenAI-compatible LLM client honoring the managed-inference contract.

The validator supplies `model`, `api_base`, and `api_key`; the agent must use only
those (no third-party keys, no overridden sampling) — same rule as ninja. An offline
stub mode (VANGUARSTEW_OFFLINE=1, or api_key == "offline", or no api_base) returns a
caller-supplied deterministic stub so the loop can be exercised without a network.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request


class LLM:
    def __init__(self, model=None, api_base=None, api_key=None, timeout=None):
        self.model = model or "validator-managed-model"
        self.api_base = (api_base or "").rstrip("/")
        self.api_key = api_key
        env_timeout = os.environ.get("TAU_AGENT_TIMEOUT_SECONDS")
        self.timeout = float(timeout or env_timeout or 120)
        self.offline = (
            os.environ.get("VANGUARSTEW_OFFLINE") == "1"
            or not self.api_base
            or self.api_key == "offline"
        )

    def chat(self, system: str, user: str) -> str:
        """Single-turn completion at temperature 0.

        Raises on transport error. Also raises ``ValueError`` when the endpoint returns a
        response that is not a well-formed chat-completion envelope (e.g. an HTTP-200 error
        body like ``{"error": ...}``, an empty ``{}``, or a bare list), so a caller that
        supplies a stub (``chat_json``) can fall back instead of crashing the agent.
        """
        if self.offline:
            return json.dumps({"_offline": True})
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        try:
            return body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError(
                f"unexpected chat-completion response envelope: {str(body)[:200]!r}"
            ) from exc

    def chat_json(self, system: str, user: str, stub=None, prefer=dict):
        """Completion parsed as JSON, with `stub` as the fallback.

        Returns `stub` verbatim in offline mode. For a live call, returns the parsed JSON —
        but when the response can't be parsed as JSON, *or* the endpoint returns a malformed
        (non-chat-completion) envelope, falls back to `stub` instead of raising, so malformed
        model output does not crash the agent (M4: no agent crashes from malformed LLM
        output). Callers already treat the stub shape as "the model gave us nothing usable".
        Transport errors from `chat` (`URLError`/`HTTPError`/`OSError`) still propagate.

        ``prefer`` declares the container type the caller's contract expects (see
        :func:`extract_json`): dict-contract callers keep the default; the planner, whose
        prompt asks for a JSON list, passes ``prefer=list`` so an echoed example object
        cannot beat the real plan array.
        """
        if self.offline:
            return stub if stub is not None else {}
        try:
            return extract_json(self.chat(system, user), prefer=prefer)
        except (ValueError, TypeError):
            return stub if stub is not None else {}


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _iter_top_level_spans(text: str):
    """Yield (opening_bracket, span_text) for each balanced `{...}`/`[...]`
    span at the top level of `text` (i.e. not nested inside a span already
    yielded). Bracket characters inside JSON string literals are ignored so
    a value like `{"note": "see [1]"}` isn't split apart."""
    i, n = 0, len(text)
    while i < n:
        opener = text[i]
        if opener not in "{[":
            i += 1
            continue
        depth = 0
        in_string = False
        escape = False
        end = None
        j = i
        while j < n:
            c = text[j]
            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
            else:
                if c == '"':
                    in_string = True
                elif c in "{[":
                    depth += 1
                elif c in "}]":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            j += 1
        if end is None:
            i += 1  # unbalanced opener; nothing usable from here
            continue
        yield opener, text[i : end + 1]
        i = end + 1


def _pick_best_json(candidates, prefer=dict):
    """Prefer ``prefer``-typed payloads (objects by default), then the longest serialization.

    When two candidates have equal rank (same tier, same serialized length),
    the *last* one wins — in an LLM response a schema example or chain-of-thought
    aside typically appears before the real answer, so the later candidate is the
    more reliable signal.  ``max`` returns the first equal-rank element, so we
    reverse the list to pick the last.

    ``prefer=list`` does NOT rank every array above every object: a list-contract
    prompt in this codebase asks for a list of *objects* (plan items), so only a
    non-empty list of dicts outranks a dict. A scalar or mixed list — a ``[1]``
    citation aside, a stray bracket span in prose — still loses to a
    ``{"plan": [...]}`` wrapper object. Ranking any list above any dict would
    just mirror the original bug: the aside would silently replace the real
    wrapper-dict answer, collapsing the scored plan the other way around.
    """
    if not candidates:
        return None

    def _rank(value):
        serialized = json.dumps(value, separators=(",", ":"))
        if prefer is list:
            if isinstance(value, list) and value and all(isinstance(i, dict) for i in value):
                tier = 2      # the contract shape: a list of plan-item objects
            elif isinstance(value, dict):
                tier = 1      # possibly a {"plan": [...]} wrapper — caller unwraps
            else:
                tier = 0      # scalar/mixed list: an aside, never the answer
        else:
            tier = int(isinstance(value, prefer))
        return (tier, len(serialized))

    return max(reversed(candidates), key=_rank)


def extract_json(text: str, prefer=dict):
    """Best-effort JSON extraction from an LLM response.

    Tries, in order: a fenced code block, the raw response verbatim, then
    balanced top-level `{...}`/`[...]` spans scanned across the text. Among
    those spans, ``prefer``-typed spans win over the other container type and,
    within a type, the longest span wins.

    ``prefer`` is the container type the *caller's contract* expects. Callers
    whose prompt asks for an object keep the default (``dict``) — a stray
    bracket-shaped aside (e.g. a `[1]` citation ahead of the real payload) must
    not be mistaken for the answer. Callers whose prompt asks for a list pass
    ``prefer=list`` — otherwise the same guard backfires: an echoed example
    object anywhere in the prose would beat the real array and silently discard
    the entire answer. ``prefer=list`` elevates only lists of objects (the
    actual contract shape); scalar/mixed lists still rank below dicts, so a
    ``[1]`` aside cannot displace a ``{"plan": [...]}`` wrapper — which is
    still returned when no object-list candidate exists (the planner unwraps
    it).
    """
    if text is None:
        raise ValueError("empty LLM response")

    fence_candidates = []
    for fence_match in _FENCE.finditer(text):
        try:
            fence_candidates.append(json.loads(fence_match.group(1)))
        except (ValueError, TypeError):
            continue
    best_fence = _pick_best_json(fence_candidates, prefer)
    if best_fence is not None:
        return best_fence

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass

    spans = []
    for opener, span in _iter_top_level_spans(text):
        try:
            value = json.loads(span)
        except (ValueError, TypeError):
            continue
        spans.append((opener, span, value))

    if spans:
        return _pick_best_json([s[2] for s in spans], prefer)

    raise ValueError(f"could not parse JSON from response: {text[:200]!r}")
