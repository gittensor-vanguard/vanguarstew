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

    def chat_json(self, system: str, user: str, stub=None, *, prefer_list=None):
        """Completion parsed as JSON, with `stub` as the fallback.

        Returns `stub` verbatim in offline mode. For a live call, returns the parsed JSON —
        but when the response can't be parsed as JSON, *or* the endpoint returns a malformed
        (non-chat-completion) envelope, falls back to `stub` instead of raising, so malformed
        model output does not crash the agent (M4: no agent crashes from malformed LLM
        output). Callers already treat the stub shape as "the model gave us nothing usable".
        Transport errors from `chat` (`URLError`/`HTTPError`/`OSError`) still propagate.

        When ``prefer_list`` is omitted, list preference is inferred from ``stub``: a list
        stub (planner) elevates plan-like arrays (non-empty lists of objects) over object
        asides; a dict stub keeps the default object-over-array ranking used by
        decide/philosophy/review. Non-plan arrays (citations) never outrank a plan
        wrapper object under either mode.
        """
        if self.offline:
            return stub if stub is not None else {}
        if prefer_list is None:
            prefer_list = isinstance(stub, list)
        try:
            return extract_json(self.chat(system, user), prefer_list=prefer_list)
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


def _is_plan_like_list(value) -> bool:
    """True for a non-empty JSON array of objects — the planner's list-contract shape.

    Citation asides like ``[1]`` and path lists like ``["a.py"]`` are deliberately
    excluded: preferring those over a ``{"plan": [...]}`` wrapper is what regressed
    live scoring under a blanket array-over-object rank (#2135).
    """
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, dict) for item in value)
    )


def _pick_best_json(candidates, *, prefer_list: bool = False):
    """Prefer the caller's expected container type, then the longest serialization.

    Default (``prefer_list=False``) ranks objects above arrays so a bracket-shaped
    aside (e.g. a ``[1]`` citation) cannot beat a dict answer.

    List-contract callers (planner) pass ``prefer_list=True``. That mode only elevates
    *plan-like* arrays (non-empty lists of objects) above objects — so an echoed
    example item cannot discard the full plan array (#1945), while a citation array
    still loses to a ``{"plan": [...]}`` wrapper (preserving pre-#2135 live behavior
    when the model returns the wrapper form).

    When two candidates have equal rank (same preferred-type bit, same serialized
    length), the *last* one wins — in an LLM response a schema example or
    chain-of-thought aside typically appears before the real answer, so the later
    candidate is the more reliable signal.  ``max`` returns the first equal-rank
    element, so we reverse the list to pick the last.
    """
    if not candidates:
        return None

    def _rank(value):
        serialized = json.dumps(value, separators=(",", ":"))
        if prefer_list:
            # 2 = plan-like list, 1 = object, 0 = other (citations / scalars lists)
            type_pref = (
                2 if _is_plan_like_list(value)
                else (1 if isinstance(value, dict) else 0)
            )
        else:
            type_pref = 1 if isinstance(value, dict) else 0
        return (type_pref, len(serialized))

    return max(reversed(candidates), key=_rank)


def extract_json(text: str, *, prefer_list: bool = False):
    """Best-effort JSON extraction from an LLM response.

    Tries, in order: a fenced code block, the raw response verbatim, then
    balanced top-level `{...}`/`[...]` spans scanned across the text. Among
    those spans, objects win by default; with ``prefer_list=True``, a plan-like
    array (non-empty list of objects) wins over objects, while non-plan arrays
    (citations, path lists) still lose to objects. Within a type tier, the
    longest span wins. When ``prefer_list=True`` and no plan-like array exists,
    the best object is still returned (e.g. a ``{"plan": [...]}`` wrapper the
    planner already unwraps).
    """
    if text is None:
        raise ValueError("empty LLM response")

    fence_candidates = []
    for fence_match in _FENCE.finditer(text):
        try:
            fence_candidates.append(json.loads(fence_match.group(1)))
        except (ValueError, TypeError):
            continue
    best_fence = _pick_best_json(fence_candidates, prefer_list=prefer_list)
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
        return _pick_best_json([s[2] for s in spans], prefer_list=prefer_list)

    raise ValueError(f"could not parse JSON from response: {text[:200]!r}")
