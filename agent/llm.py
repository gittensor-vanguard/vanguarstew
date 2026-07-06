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


def extract_json(text: str):
    """Best-effort JSON extraction from an LLM response (handles code fences).

    When a response contains more than one fenced code block -- a verbose/chain-of-
    thought model can restate a schema example in an earlier fence before its real
    answer in a later one -- fences are tried last-to-first, so the final (most
    likely genuine) fenced answer is preferred over an earlier throwaway example.
    """
    if text is None:
        raise ValueError("empty LLM response")
    candidates = [text]
    fences = [m.group(1) for m in _FENCE.finditer(text)]
    candidates = list(reversed(fences)) + candidates
    # also try the first {...} or [...] span
    brace = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if brace:
        candidates.append(brace.group(1))
    for c in candidates:
        try:
            return json.loads(c)
        except (ValueError, TypeError):
            continue
    raise ValueError(f"could not parse JSON from response: {text[:200]!r}")
