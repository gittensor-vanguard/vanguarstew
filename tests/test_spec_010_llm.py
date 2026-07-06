"""Contract tests for specs/010-agent-llm — assert llm.py satisfies the spec's EARS criteria:
managed-inference parameter handling, offline chat/chat_json stub behavior, extract_json
parsing order, and tie-break rules. Offline, deterministic; no network is used.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm import LLM, _pick_best_json, extract_json  # noqa: E402

# --- Managed-inference parameters -----------------------------------------------------------

def test_offline_when_vanguarstew_offline_env_is_set(monkeypatch):
    monkeypatch.setenv("VANGUARSTEW_OFFLINE", "1")
    llm = LLM(model="m", api_base="https://api.example.com", api_key="secret")
    assert llm.offline is True
    assert llm.model == "m"
    assert llm.api_key == "secret"


def test_offline_when_api_base_missing_or_blank():
    assert LLM(api_base=None).offline is True
    assert LLM(api_base="").offline is True
    assert LLM(api_base="   ").offline is True


def test_offline_when_api_key_is_offline():
    llm = LLM(api_base="https://api.example.com", api_key="offline")
    assert llm.offline is True


def test_api_base_trailing_slash_is_stripped():
    llm = LLM(api_base="https://api.example.com/", api_key="offline")
    assert llm.api_base == "https://api.example.com"


def test_online_when_base_and_key_provided_and_offline_env_unset(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="gpt-test", api_base="https://api.example.com", api_key="secret")
    assert llm.offline is False
    assert llm.model == "gpt-test"


# --- Offline chat() behavior ----------------------------------------------------------------

def test_offline_chat_returns_offline_marker_json(monkeypatch):
    monkeypatch.setenv("VANGUARSTEW_OFFLINE", "1")
    raw = LLM(api_base="https://api.example.com", api_key="k").chat("system", "user")
    assert json.loads(raw) == {"_offline": True}


# --- Offline chat_json() behavior -----------------------------------------------------------

@pytest.mark.parametrize("stub,expected", [
    ({"action": "plan", "labels": []}, {"action": "plan", "labels": []}),
    ([1, 2, 3], [1, 2, 3]),
    ("verbatim string", "verbatim string"),
])
def test_offline_chat_json_returns_stub_verbatim(stub, expected, monkeypatch):
    monkeypatch.setenv("VANGUARSTEW_OFFLINE", "1")
    out = LLM(api_key="offline").chat_json("system", "user", stub=stub)
    assert out == expected
    assert out is stub


def test_offline_chat_json_returns_empty_dict_when_stub_is_none(monkeypatch):
    monkeypatch.setenv("VANGUARSTEW_OFFLINE", "1")
    assert LLM(api_key="offline").chat_json("system", "user", stub=None) == {}


# --- Live chat_json() resilience to malformed output ----------------------------------------

def _live_llm(monkeypatch, reply):
    """A non-offline LLM whose transport returns ``reply`` verbatim (no network)."""
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="secret")
    assert llm.offline is False
    llm.chat = lambda system, user: reply
    return llm


def test_chat_json_falls_back_to_stub_on_unparseable_output(monkeypatch):
    # Malformed model output (no JSON anywhere) must not crash the agent: fall back to the stub
    # (M4 acceptance: no agent crashes from malformed LLM output).
    llm = _live_llm(monkeypatch, "Sure, I'd merge it. (no JSON here)")
    stub = {"action": "plan", "labels": []}
    assert llm.chat_json("system", "user", stub=stub) == stub


def test_chat_json_falls_back_to_empty_dict_when_stub_is_none(monkeypatch):
    llm = _live_llm(monkeypatch, "no json at all")
    assert llm.chat_json("system", "user", stub=None) == {}


def test_chat_json_returns_parsed_json_when_output_is_valid(monkeypatch):
    llm = _live_llm(monkeypatch, 'Here you go:\n```json\n{"action": "merge"}\n```')
    assert llm.chat_json("system", "user", stub={"action": "plan"}) == {"action": "merge"}


def test_chat_json_still_propagates_a_transport_error(monkeypatch):
    # Only a parse failure falls back to the stub; a transport/connection error must still raise.
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="secret")

    def boom(system, user):
        raise ConnectionError("network down")

    llm.chat = boom
    with pytest.raises(ConnectionError):
        llm.chat_json("system", "user", stub={"action": "plan"})


# --- Live chat() envelope handling (real chat(), HTTP transport mocked) ---------------------

class _FakeResp:
    """Minimal context-manager stand-in for an ``http.client.HTTPResponse``."""

    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _online_llm(monkeypatch, body):
    """A non-offline LLM whose HTTP transport returns ``body`` verbatim (no network)."""
    import urllib.request

    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="secret")
    assert llm.offline is False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(body))
    return llm


def test_chat_returns_content_from_a_valid_envelope(monkeypatch):
    body = '{"choices": [{"message": {"content": "hello"}}]}'
    assert _online_llm(monkeypatch, body).chat("system", "user") == "hello"


@pytest.mark.parametrize("body", [
    '{"error": {"message": "overloaded"}}',   # HTTP-200 error envelope (common on overload)
    "{}",                                      # empty object — no choices
    "[]",                                      # bare list — wrong shape entirely
    "not json at all",                         # not even JSON
])
def test_chat_raises_valueerror_on_malformed_envelope(body, monkeypatch):
    # A malformed (non-chat-completion) 200 body is malformed model output, not a transport
    # error: chat() raises ValueError (never KeyError/IndexError/TypeError) so chat_json can
    # fall back to the stub.
    with pytest.raises(ValueError):
        _online_llm(monkeypatch, body).chat("system", "user")


@pytest.mark.parametrize("body", [
    '{"error": {"message": "overloaded"}}',
    "{}",
    "[]",
    "not json at all",
])
def test_chat_json_falls_back_to_stub_on_malformed_envelope(body, monkeypatch):
    # M4 acceptance: a malformed inference-response envelope must not crash the agent — it
    # falls back to the stub, exactly like unparseable content does (regression for #954).
    stub = {"action": "plan", "labels": []}
    assert _online_llm(monkeypatch, body).chat_json("system", "user", stub=stub) == stub


# --- JSON extraction order ------------------------------------------------------------------

def test_extract_json_parses_fenced_code_block():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('```\n{"b": 2}\n```') == {"b": 2}


def test_extract_json_parses_raw_response_verbatim():
    assert extract_json('{"x": [1, 2]}') == {"x": [1, 2]}


def test_extract_json_parses_balanced_top_level_span_in_prose():
    assert extract_json('noise {"x": [1, 2]} trailing') == {"x": [1, 2]}


def test_extract_json_respects_string_literals_inside_spans():
    text = 'prefix {"note": "see [1] for details", "ok": true} suffix'
    assert extract_json(text) == {"note": "see [1] for details", "ok": True}


def test_extract_json_raises_on_none_text():
    with pytest.raises(ValueError, match="empty LLM response"):
        extract_json(None)


def test_extract_json_raises_when_no_valid_candidate():
    with pytest.raises(ValueError, match="could not parse JSON"):
        extract_json("no json here at all, just [Doe, 2020] prose")


# --- JSON candidate tie-breaking ------------------------------------------------------------

def test_pick_best_json_prefers_dict_over_list():
    best = _pick_best_json([{"a": 1}, [1, 2, 3, 4, 5, 6]])
    assert best == {"a": 1}


def test_pick_best_json_prefers_longest_serialized_form():
    best = _pick_best_json([{"a": 1}, {"a": 1, "b": 2, "c": 3}])
    assert best == {"a": 1, "b": 2, "c": 3}


def test_pick_best_json_equal_rank_prefers_last_candidate():
    candidates = [{"action": "praise", "score": 1}, {"action": "reject", "score": 6}]
    assert _pick_best_json(candidates) == {"action": "reject", "score": 6}


def test_extract_json_prefers_object_over_leading_citation_array():
    text = '[1] the agent decided: {"decision": "approve", "confidence": 0.9}'
    assert extract_json(text) == {"decision": "approve", "confidence": 0.9}


def test_extract_json_multiple_arrays_prefers_longest():
    text = "first [1] then [2, 3] and finally [4, 5, 6]"
    assert extract_json(text) == [4, 5, 6]


def test_extract_json_prefers_later_fenced_object_over_earlier_schema_example():
    text = (
        "Example:\n```json\n"
        '{"action": "merge", "labels": [], "reviewer": null, '
        '"version_bump": null, "patch": null, "rationale": "example"}\n'
        "```\n\nReal:\n```json\n"
        '{"action": "reject", "labels": ["needs-tests"], "reviewer": "alice", '
        '"version_bump": null, "patch": null, "rationale": "missing tests"}\n'
        "```"
    )
    assert extract_json(text) == {
        "action": "reject",
        "labels": ["needs-tests"],
        "reviewer": "alice",
        "version_bump": None,
        "patch": None,
        "rationale": "missing tests",
    }


def test_extract_json_equal_rank_fenced_blocks_prefer_last():
    text = (
        'Example:\n```json\n{"action":"praise","score":1}\n```\n\n'
        'Real:\n```json\n{"action":"reject","score":6}\n```'
    )
    assert extract_json(text) == {"action": "reject", "score": 6}


# --- Robustness -----------------------------------------------------------------------------

def test_extract_json_skips_invalid_fenced_block_and_uses_valid_one():
    text = 'bad ```json\n{not json}\n``` good ```json\n{"ok": true}\n```'
    assert extract_json(text) == {"ok": True}


def test_extract_json_skips_invalid_citation_span_and_uses_later_object():
    text = 'see [Doe, 2020] for background — result: {"ok": true}'
    assert extract_json(text) == {"ok": True}


def test_extract_json_nested_object_span():
    text = 'prefix {"a": {"b": [1, 2, 3]}, "c": true} suffix'
    assert extract_json(text) == {"a": {"b": [1, 2, 3]}, "c": True}
