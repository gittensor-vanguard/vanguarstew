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
        """Single-turn completion at temperature 0. Raises on transport error."""
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
        return body["choices"][0]["message"]["content"]

    def chat_json(self, system: str, user: str, stub=None):
        """Completion parsed as JSON. In offline mode, returns `stub` verbatim."""
        if self.offline:
            return stub if stub is not None else {}
        return extract_json(self.chat(system, user))


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


def extract_json(text: str):
    """Best-effort JSON extraction from an LLM response.

    Tries, in order: fenced code blocks, the raw response verbatim, then
    balanced top-level `{...}`/`[...]` spans scanned across the text. When
    multiple fenced blocks (or, failing that, multiple spans) parse as valid
    JSON — a verbose/chain-of-thought response can restate a schema example
    in an earlier fence before its real answer in a later one — object
    candidates are preferred over array candidates and, within a type, the
    longest candidate wins. This keeps a stray bracket-shaped aside (e.g. a
    `[1]` citation) or a throwaway earlier example from being mistaken for
    the real, more complete answer, while still supporting genuine array
    responses.
    """
    if text is None:
        raise ValueError("empty LLM response")

    fence_candidates = []
    for fence_match in _FENCE.finditer(text):
        block = fence_match.group(1)
        try:
            value = json.loads(block)
        except (ValueError, TypeError):
            continue
        opener = "{" if isinstance(value, dict) else "["
        fence_candidates.append((opener, block, value))
    if fence_candidates:
        fence_candidates.sort(key=lambda c: (c[0] != "{", -len(c[1])))
        return fence_candidates[0][2]

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
        spans.sort(key=lambda s: (s[0] != "{", -len(s[1])))
        return spans[0][2]

    raise ValueError(f"could not parse JSON from response: {text[:200]!r}")
