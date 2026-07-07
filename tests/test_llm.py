"""Unit tests for agent/llm.py — managed-inference client and offline stub."""

import json
import os
import sys
from unittest import mock

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


def test_offline_chat_returns_deterministic_stub():
    llm = LLM(api_key="offline")
    first = llm.chat("system prompt", "user prompt")
    second = llm.chat("other system", "other user")
    assert first == second == json.dumps({"_offline": True})


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
