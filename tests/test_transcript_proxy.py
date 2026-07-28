"""Regression tests for the transcript-proxy request/upstream error handling (issue #2061).

The proxy is the Phase-0 evidence mechanism (record/replay of every model call, per #1935). Its
record path must fail loudly but *cleanly* — a clean HTTP error, never an uncaught handler crash —
so a benign upstream error or a malformed request can't take the recorder down mid-run or silently
corrupt the transcript. These tests drive a real server over a socket.
"""

import http.client
import json
import os
import socket
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.transcript_proxy as proxy  # noqa: E402
from benchmark.transcript import TranscriptStore  # noqa: E402


class _FakeResp:
    """A urlopen() context-manager stand-in returning a fixed JSON payload."""

    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, *args):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _RunningProxy:
    def __init__(self, mode, upstream="", store=None):
        self.store = store if store is not None else TranscriptStore()
        # port 0 -> the OS picks a free port; read it back from the bound server.
        self.server = proxy.build_server(mode, 0, upstream, self.store)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def post(self, body, headers=None, path="/v1/chat/completions"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", path, body=json.dumps(body), headers=headers or {})
        resp = conn.getresponse()
        status, data = resp.status, resp.read()
        conn.close()
        return status, data

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


@pytest.fixture
def _valid_request():
    return {"model": "m", "messages": [{"role": "user", "content": "hi"}]}


# ---- record mode: unexpected upstream response shape -> clean 502 --------------------------


@pytest.mark.parametrize("bad_payload", [
    {"error": {"message": "rate limited"}},   # an error envelope (HTTP 200 body)
    {"choices": []},                          # empty choices -> IndexError
    {"choices": [{"message": {}}]},           # missing content -> KeyError
    {},                                       # missing choices -> KeyError
])
def test_record_mode_returns_502_on_unexpected_upstream_shape(monkeypatch, _valid_request, bad_payload):
    monkeypatch.setattr(proxy.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(bad_payload))
    server = _RunningProxy("record", upstream="https://api.example/v1")
    try:
        status, data = server.post(_valid_request)
        assert status == 502
        assert b"upstream call failed" in data
        # the server survived the bad upstream and still serves the next request
        status2, _ = server.post(_valid_request)
        assert status2 == 502
        # nothing was recorded from a failed upstream call
        assert len(server.store) == 0
    finally:
        server.close()


def test_record_mode_records_a_well_formed_response(monkeypatch, _valid_request):
    good = {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    monkeypatch.setattr(proxy.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp(good))
    server = _RunningProxy("record", upstream="https://api.example/v1")
    try:
        status, data = server.post(_valid_request)
        assert status == 200
        assert json.loads(data)["choices"][0]["message"]["content"] == "hello"
        assert len(server.store) == 1
    finally:
        server.close()


# ---- malformed Content-Length -> clean 400 -------------------------------------------------


def test_malformed_content_length_returns_400():
    server = _RunningProxy("replay")
    try:
        raw = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        raw.sendall(
            b"POST /v1/chat/completions HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Length: not-a-number\r\n"
            b"\r\n"
        )
        reply = raw.recv(4096)
        raw.close()
        assert b" 400 " in reply
        assert b"invalid Content-Length" in reply
    finally:
        server.close()


# ---- existing clean-error contract still holds ---------------------------------------------


def test_replay_miss_returns_409(_valid_request):
    server = _RunningProxy("replay")  # empty store -> every request is a miss
    try:
        status, data = server.post(_valid_request)
        assert status == 409
        assert b"no recorded response" in data
    finally:
        server.close()


def test_unsupported_path_returns_404(_valid_request):
    server = _RunningProxy("replay")
    try:
        status, _ = server.post(_valid_request, path="/v1/embeddings")
        assert status == 404
    finally:
        server.close()
