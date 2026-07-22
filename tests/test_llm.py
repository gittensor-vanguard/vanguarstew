"""Unit tests for agent/llm.py — managed-inference client and offline stub."""

import json
import os
import sys
from unittest import mock

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm import LLM  # noqa: E402


class _FakeResp:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _online(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="secret")
    assert llm.offline is False
    return llm


# ---- Construction -----------------------------------------------------------

def test_llm_constructs_with_managed_inference_params(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(
        api_base="https://stub.example",
        api_key="stub-key",
        model="stub-model",
    )
    assert llm.model == "stub-model"
    assert llm.api_base == "https://stub.example"
    assert llm.api_key == "stub-key"
    assert llm.offline is False


def test_constructs_defaults_when_no_args():
    llm = LLM()
    assert llm.model == "validator-managed-model"
    assert llm.api_base == ""
    assert llm.api_key is None


# ---- Offline mode -----------------------------------------------------------

def test_offline_chat_returns_deterministic_stub():
    llm = LLM(api_key="offline")
    first = llm.chat("system prompt", "user prompt")
    second = llm.chat("other system", "other user")
    assert first == second == json.dumps({"_offline": True})


def test_offline_when_no_api_base():
    assert LLM(api_base=None).offline is True
    assert LLM(api_base="").offline is True


# ---- Timeout ----------------------------------------------------------------

def test_timeout_defaults_to_120():
    assert LLM().timeout == 120.0


def test_timeout_from_constructor():
    assert LLM(timeout=30).timeout == 30.0


def test_timeout_from_env(monkeypatch):
    monkeypatch.setenv("TAU_AGENT_TIMEOUT_SECONDS", "45")
    assert LLM().timeout == 45.0


def test_timeout_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("TAU_AGENT_TIMEOUT_SECONDS", "45")
    assert LLM(timeout=10).timeout == 10.0


def test_chat_passes_timeout_to_urlopen(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    monkeypatch.delenv("TAU_AGENT_TIMEOUT_SECONDS", raising=False)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        return _FakeResp('{"choices": [{"message": {"content": "ok"}}]}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    llm = LLM(
        model="m",
        api_base="https://api.example.com",
        api_key="secret",
        timeout=42.5,
    )
    assert llm.chat("system", "user") == "ok"
    assert captured["timeout"] == 42.5


def test_chat_returns_content_from_valid_http_200_envelope(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    body = '{"choices": [{"message": {"content": "hello from model"}}]}'
    with mock.patch(
        "urllib.request.urlopen",
        return_value=_FakeResp(body),
    ) as urlopen_mock:
        llm = LLM(
            model="m",
            api_base="https://api.example.com",
            api_key="secret",
        )
        assert llm.offline is False
        assert llm.chat("system", "user") == "hello from model"
        urlopen_mock.assert_called_once()
        _, kwargs = urlopen_mock.call_args
        assert kwargs["timeout"] == llm.timeout


# ---- Response validation (mocked HTTP) --------------------------------------

def test_chat_raises_valueerror_on_http200_error_object(monkeypatch):
    body = '{"error": {"message": "model overloaded", "type": "server_error"}}'
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
            _online(monkeypatch).chat("s", "u")


def test_chat_raises_valueerror_on_empty_object(monkeypatch):
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp("{}")):
        with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
            _online(monkeypatch).chat("s", "u")


def test_chat_raises_valueerror_on_bare_array(monkeypatch):
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp("[]")):
        with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
            _online(monkeypatch).chat("s", "u")


def test_chat_raises_on_non_json_response_body(monkeypatch):
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp("not json at all")):
        with pytest.raises(json.JSONDecodeError):
            _online(monkeypatch).chat("s", "u")


# ---- chat_json fallback -----------------------------------------------------

def test_chat_json_falls_back_to_stub_on_malformed_envelope(monkeypatch):
    stub = {"action": "plan", "labels": []}
    llm = _online(monkeypatch)
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp("{}")):
        assert llm.chat_json("s", "u", stub=stub) == stub


def test_chat_json_falls_back_to_empty_dict_when_no_stub(monkeypatch):
    llm = _online(monkeypatch)
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp("[]")):
        assert llm.chat_json("s", "u", stub=None) == {}


def test_chat_json_propagates_transport_error(monkeypatch):
    llm = _online(monkeypatch)

    def boom(system, user):
        raise ConnectionError("timeout")

    llm.chat = boom
    with pytest.raises(ConnectionError):
        llm.chat_json("s", "u", stub={"action": "plan"})


def test_chat_json_returns_parsed_json_from_valid_envelope(monkeypatch):
    body = '{"choices": [{"message": {"content": "{\\"action\\": \\"merge\\"}"}}]}'
    llm = _online(monkeypatch)
    with mock.patch("urllib.request.urlopen", return_value=_FakeResp(body)):
        assert llm.chat_json("s", "u") == {"action": "merge"}


# ---- caller-declared shape (prefer=) ---------------------------------------

_PLAN_REPLY = (
    "Here is an example item shape:\n"
    '{"title": "Fix the loader race", "kind": "bugfix"}\n\n'
    "And the full plan:\n"
    '[{"title": "Fix quick-router crash", "kind": "bugfix", "files": ["router.py"]},\n'
    ' {"title": "Cut v1.4.0", "kind": "release", "files": []},\n'
    ' {"title": "Refactor plugin loader", "kind": "refactor", "files": ["loader.py"]}]'
)


def test_extract_json_prefer_list_keeps_plan_array_over_echoed_example_object():
    # A list-contract caller must get the real plan array, not the echoed example
    # object that precedes it — the default dict-over-array guard would otherwise
    # discard the entire scored plan.
    from agent.llm import extract_json

    picked = extract_json(_PLAN_REPLY, prefer=list)
    assert isinstance(picked, list)
    assert len(picked) == 3
    assert picked[0]["title"] == "Fix quick-router crash"


def test_extract_json_default_still_prefers_object():
    # Dict-contract callers are unchanged: the object wins by default.
    from agent.llm import extract_json

    picked = extract_json(_PLAN_REPLY)
    assert picked == {"title": "Fix the loader race", "kind": "bugfix"}


def test_extract_json_prefer_list_still_returns_object_when_no_array():
    # A {"plan": [...]} wrapper reply to a list-contract prompt is still surfaced
    # (the planner unwraps it); prefer= is a preference, not a filter.
    from agent.llm import extract_json

    text = 'Sure: {"plan": [{"title": "t", "kind": "docs"}]}'
    assert extract_json(text, prefer=list) == {"plan": [{"title": "t", "kind": "docs"}]}


def test_extract_json_prefer_list_in_fenced_blocks():
    # The same preference applies to fenced candidates, where an example object
    # fence would otherwise beat the real plan-array fence.
    from agent.llm import extract_json

    text = (
        "Example item:\n```json\n"
        '{"title": "example", "kind": "bugfix"}\n'
        "```\nFull plan:\n```json\n"
        '[{"title": "real1", "kind": "docs"}, {"title": "real2", "kind": "test"}]\n'
        "```"
    )
    picked = extract_json(text, prefer=list)
    assert [i["title"] for i in picked] == ["real1", "real2"]


def test_pick_best_json_prefer_list_ranks_array_first():
    from agent.llm import _pick_best_json

    best = _pick_best_json([{"a": 1}, [1, 2, 3]], prefer=list)
    assert best == [1, 2, 3]


def test_chat_json_threads_prefer_through_to_extraction(monkeypatch):
    llm = _online(monkeypatch)
    llm.chat = lambda system, user: _PLAN_REPLY
    picked = llm.chat_json("s", "u", stub=[], prefer=list)
    assert isinstance(picked, list)
    assert len(picked) == 3
