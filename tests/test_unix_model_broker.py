"""Regression tests for the isolated model broker's upstream-URL policy (issue #2047).

`UnixModelBroker` keeps the real API key outside an untrusted candidate container and forces a
fixed upstream. Routing model calls through a local transcript recorder (Phase 0 of #1935) means
the broker must accept a **loopback HTTP** recorder while still requiring **HTTPS** for any remote
upstream and rejecting URL-embedded credentials. The policy lives in the constructor (no server is
started), so these tests are hermetic.

`tests/test_docker_solve_adapter.py` covers the happy-path relay and one loopback-accept /
plaintext-remote-reject pair; this suite pins the rest of the taxonomy — the security-critical
credential-injection cases, IPv6 loopback, and the malformed-input rejections.
"""

import json
import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.unix_model_broker import ModelBrokerError, UnixModelBroker  # noqa: E402


def _make(tmp_path, api_base, name="broker.sock", **kw):
    kw.setdefault("api_key", "host-only-key")
    kw.setdefault("model", "fixed-model")
    return UnixModelBroker(socket_path=tmp_path / name, api_base=api_base, **kw)


# ---- accepted upstreams --------------------------------------------------------------------


@pytest.mark.parametrize("api_base", [
    "https://api.example/v1",
    "https://api.openai.com",
    "HTTPS://API.EXAMPLE/v1",           # scheme/host are case-insensitive
])
def test_https_remote_is_accepted(tmp_path, api_base):
    broker = _make(tmp_path, api_base)
    assert broker.api_base == api_base.rstrip("/")


@pytest.mark.parametrize("api_base", [
    "http://127.0.0.1:18081/v1",        # IPv4 loopback recorder
    "http://[::1]:18081/v1",            # IPv6 loopback recorder
])
def test_loopback_http_recorder_is_accepted(tmp_path, api_base):
    broker = _make(tmp_path, api_base)
    assert broker.api_base == api_base


def test_trailing_slash_is_normalized(tmp_path):
    assert _make(tmp_path, "https://api.example/v1/").api_base == "https://api.example/v1"


# ---- rejected upstreams --------------------------------------------------------------------


@pytest.mark.parametrize("api_base", [
    "http://10.0.0.5:18081/v1",         # a non-loopback plaintext remote
    "http://api.example/v1",            # plaintext remote by name
    "http://localhost:18081/v1",        # only literal loopback IPs, never the "localhost" name
    "ftp://127.0.0.1/v1",               # non-http(s) scheme
    "https://",                         # no host
    "//127.0.0.1/v1",                   # scheme-relative (no scheme)
])
def test_non_https_non_loopback_upstreams_are_rejected(tmp_path, api_base):
    with pytest.raises(ModelBrokerError, match="HTTPS or trusted loopback"):
        _make(tmp_path, api_base)


@pytest.mark.parametrize("api_base", [
    "https://user:pass@api.example/v1",     # credentials on an HTTPS upstream
    "https://user@api.example/v1",          # username only
    "http://evil.com@127.0.0.1:18081/v1",   # credential injection with a loopback host
    "http://127.0.0.1@evil.com/v1",         # loopback smuggled into the userinfo, real host remote
])
def test_url_embedded_credentials_are_rejected(tmp_path, api_base):
    with pytest.raises(ModelBrokerError, match="HTTPS or trusted loopback"):
        _make(tmp_path, api_base)


@pytest.mark.parametrize("api_base", [
    "https://api.example/v1?token=abc",     # a query string on the base
    "https://api.example/v1#frag",          # a fragment
])
def test_query_or_fragment_on_the_upstream_is_rejected(tmp_path, api_base):
    with pytest.raises(ModelBrokerError, match="HTTPS or trusted loopback"):
        _make(tmp_path, api_base)


@pytest.mark.parametrize("api_base", [None, 42, b"https://api.example", ["https://x"]])
def test_a_non_string_upstream_is_rejected_without_crashing(tmp_path, api_base):
    with pytest.raises(ModelBrokerError, match="HTTPS or trusted loopback"):
        _make(tmp_path, api_base)


# ---- other constructor guards --------------------------------------------------------------


@pytest.mark.parametrize("api_key,model", [("", "m"), ("k", ""), (None, "m"), ("k", None)])
def test_missing_key_or_model_is_rejected(tmp_path, api_key, model):
    with pytest.raises(ModelBrokerError, match="key and model are required"):
        UnixModelBroker(socket_path=tmp_path / "b.sock", api_base="https://api.example/v1",
                        api_key=api_key, model=model)


def test_a_preexisting_socket_path_is_rejected(tmp_path):
    existing = tmp_path / "taken.sock"
    existing.write_text("")
    with pytest.raises(ModelBrokerError, match="already exists"):
        UnixModelBroker(socket_path=existing, api_base="https://api.example/v1",
                        api_key="k", model="m")


# ---- functional: a loopback-configured broker actually relays through the recorder ----------


def test_loopback_broker_relays_and_hides_the_key(tmp_path):
    # Prove the loopback acceptance is end-to-end, not just a constructor check: a candidate's
    # call over the Unix socket is forwarded to the (loopback recorder) upstream with the host's
    # key injected and the fixed model forced -- exactly the transcript-recording path of #2047.
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.data.decode("utf-8"))

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, *a):
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        return _Resp()

    socket_path = tmp_path / "broker.sock"
    broker = UnixModelBroker(
        socket_path=socket_path, api_base="http://127.0.0.1:18081/v1",
        api_key="host-only-key", model="fixed-model", opener=opener,
    )
    body = b'{"messages":[{"role":"user","content":"hi"}]}'
    request = (
        b"POST /chat/completions HTTP/1.1\r\nHost: broker\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )
    try:
        with broker:
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client.connect(str(socket_path))
            client.sendall(request)
            reply = client.recv(4096)
            client.close()
    except (PermissionError, OSError):
        pytest.skip("execution sandbox does not permit Unix-socket bind/connect")

    assert b" 200 " in reply
    assert seen["url"] == "http://127.0.0.1:18081/v1/chat/completions"
    assert seen["authorization"] == "Bearer host-only-key"
    assert seen["body"]["model"] == "fixed-model"
