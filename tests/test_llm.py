"""Tests for the managed-inference client (agent/llm.py). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest tests/test_llm.py -q
"""

import json
import os
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm import LLM  # noqa: E402

# ---- Construction ---------------------------------------------------------


def test_constructs_with_stub_params():
    llm = LLM(api_base="https://api.example.com", api_key="sk-test", model="gpt-4")
    assert llm.model == "gpt-4"
    assert llm.api_base == "https://api.example.com"
    assert llm.api_key == "sk-test"


def test_constructs_defaults_when_no_args():
    llm = LLM()
    assert llm.model == "validator-managed-model"
    assert llm.api_base == ""
    assert llm.api_key is None


# ---- Offline mode ---------------------------------------------------------


def test_offline_mode_deterministic_stub(monkeypatch):
    monkeypatch.setenv("VANGUARSTEW_OFFLINE", "1")
    llm = LLM(api_base="https://api.example.com", api_key="k")
    raw = llm.chat("system prompt", "user message")
    assert json.loads(raw) == {"_offline": True}


def test_offline_when_api_key_is_offline_literal():
    llm = LLM(api_base="https://api.example.com", api_key="offline")
    assert llm.offline is True


def test_offline_when_no_api_base():
    assert LLM(api_base=None).offline is True
    assert LLM(api_base="").offline is True


# ---- Timeout --------------------------------------------------------------


def test_timeout_defaults_to_120():
    llm = LLM()
    assert llm.timeout == 120.0


def test_timeout_from_constructor():
    llm = LLM(timeout=30)
    assert llm.timeout == 30.0


def test_timeout_from_env(monkeypatch):
    monkeypatch.setenv("TAU_AGENT_TIMEOUT_SECONDS", "45")
    llm = LLM()
    assert llm.timeout == 45.0


def test_timeout_constructor_overrides_env(monkeypatch):
    monkeypatch.setenv("TAU_AGENT_TIMEOUT_SECONDS", "45")
    llm = LLM(timeout=10)
    assert llm.timeout == 10.0


def test_timeout_is_passed_to_urlopen(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="k", timeout=7)
    assert llm.offline is False

    called_with = {}

    def fake_urlopen(req, timeout=None):
        called_with["timeout"] = timeout
        raise ConnectionError("stop before reading body")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ConnectionError):
        llm.chat("system", "user")
    assert called_with["timeout"] == 7


# ---- Response validation (mocked HTTP) -----------------------------------


class _FakeResp:
    def __init__(self, body):
        self._b = body.encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _online_llm(monkeypatch, body, timeout=None):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="k", timeout=timeout)
    assert llm.offline is False
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: _FakeResp(body))
    return llm


def test_chat_returns_content_from_valid_envelope(monkeypatch):
    body = '{"choices": [{"message": {"content": "merge this PR"}}]}'
    assert _online_llm(monkeypatch, body).chat("s", "u") == "merge this PR"


def test_chat_raises_valueerror_on_http200_error_object(monkeypatch):
    body = '{"error": {"message": "model overloaded", "type": "server_error"}}'
    with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
        _online_llm(monkeypatch, body).chat("s", "u")


def test_chat_raises_valueerror_on_empty_object(monkeypatch):
    with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
        _online_llm(monkeypatch, "{}").chat("s", "u")


def test_chat_raises_valueerror_on_bare_array(monkeypatch):
    with pytest.raises(ValueError, match="unexpected chat-completion response envelope"):
        _online_llm(monkeypatch, "[]").chat("s", "u")


def test_chat_raises_on_non_json_response_body(monkeypatch):
    with pytest.raises(json.JSONDecodeError):
        _online_llm(monkeypatch, "not json at all").chat("s", "u")


# ---- chat_json fallback ---------------------------------------------------


def test_chat_json_falls_back_to_stub_on_malformed_envelope(monkeypatch):
    stub = {"action": "plan", "labels": []}
    result = _online_llm(monkeypatch, "{}").chat_json("s", "u", stub=stub)
    assert result == stub


def test_chat_json_falls_back_to_empty_dict_when_no_stub(monkeypatch):
    assert _online_llm(monkeypatch, "[]").chat_json("s", "u", stub=None) == {}


def test_chat_json_propagates_transport_error(monkeypatch):
    monkeypatch.delenv("VANGUARSTEW_OFFLINE", raising=False)
    llm = LLM(model="m", api_base="https://api.example.com", api_key="k")

    def boom(system, user):
        raise ConnectionError("timeout")

    llm.chat = boom
    with pytest.raises(ConnectionError):
        llm.chat_json("s", "u", stub={"action": "plan"})


def test_chat_json_returns_parsed_json_from_valid_envelope(monkeypatch):
    body = '{"choices": [{"message": {"content": "{\\"action\\": \\"merge\\"}"}}]}'
    assert _online_llm(monkeypatch, body).chat_json("s", "u") == {"action": "merge"}
