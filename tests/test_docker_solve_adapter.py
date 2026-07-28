"""Security-contract tests for networkless candidate execution and its fixed model broker."""

import json
import os
import socket
from types import SimpleNamespace

import pytest

from benchmark.docker_solve_adapter import SANDBOX_IMAGE, DockerSolveAdapter
from benchmark.unix_model_broker import ModelBrokerError, UnixModelBroker


def _socket(path):
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(path))
    except PermissionError:
        server.close()
        pytest.skip("execution sandbox does not permit Unix-socket bind")
    return server


def test_adapter_command_has_no_network_secrets_or_writable_source_mounts(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    (candidate / "agent.py").write_text("def solve(**kwargs): return {}\n", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    broker_path = tmp_path / "model.sock"
    broker = _socket(broker_path)
    seen = {}

    def executor(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        kwargs["stdout"].write(b'VANGUARSTEW_SANDBOX_RESULT={"plan":[]}\n')
        return SimpleNamespace(returncode=0)

    try:
        adapter = DockerSolveAdapter(
            candidate_root=candidate, broker_socket=broker_path, executor=executor,
        )
        result = adapter(
            repo_path=repo, request="plan", model="fixed-model",
            api_base="https://must-not-enter.invalid", api_key="super-secret", n=3,
        )
    finally:
        broker.close()

    assert result == {"plan": []}
    command = seen["command"]
    rendered = " ".join(command)
    assert command[:4] == ["docker", "run", "--rm", "--network=none"]
    assert "--read-only" in command
    assert "--cap-drop=ALL" in command
    assert "--security-opt=no-new-privileges" in command
    assert SANDBOX_IMAGE in command
    assert "super-secret" not in rendered
    assert "must-not-enter" not in rendered
    assert "dst=/candidate,readonly" in rendered
    assert "dst=/workspace,readonly" in rendered
    assert seen["kwargs"]["env"] == {"PATH": os.environ.get("PATH", "")}


class _UpstreamResponse:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return b'{"choices":[{"message":{"content":"ok"}}]}'


def test_unix_broker_forces_fixed_https_upstream_model_and_hides_key(tmp_path):
    socket_path = tmp_path / "broker.sock"
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.data)
        return _UpstreamResponse()

    broker = UnixModelBroker(
        socket_path=socket_path, api_base="https://api.example/v1", api_key="host-only-key",
        model="fixed-model", opener=opener,
    )
    try:
        broker.__enter__()
    except PermissionError:
        pytest.skip("execution sandbox does not permit Unix-socket bind")
    try:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(socket_path))
        body = json.dumps({"model": "attacker-choice", "messages": [{"role": "user", "content": "x"}]})
        request = (
            "POST /chat/completions HTTP/1.1\r\nHost: local\r\n"
            f"Content-Length: {len(body.encode())}\r\nContent-Type: application/json\r\n\r\n{body}"
        )
        client.sendall(request.encode())
        response = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            response += chunk
        client.close()
    finally:
        broker.__exit__(None, None, None)

    assert b"200 OK" in response
    assert seen["url"] == "https://api.example/v1/chat/completions"
    assert seen["authorization"] == "Bearer host-only-key"
    assert seen["body"]["model"] == "fixed-model"
    assert not socket_path.exists()


def test_broker_allows_local_transcript_proxy_but_rejects_plaintext_remote(tmp_path):
    broker = UnixModelBroker(
        socket_path=tmp_path / "unused.sock",
        api_base="http://127.0.0.1:18081/v1",
        api_key="host-only-key",
        model="fixed-model",
    )
    assert broker.api_base == "http://127.0.0.1:18081/v1"
    with pytest.raises(ModelBrokerError, match="HTTPS or trusted loopback"):
        UnixModelBroker(
            socket_path=tmp_path / "other.sock",
            api_base="http://api.example/v1",
            api_key="host-only-key",
            model="fixed-model",
        )
