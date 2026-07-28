"""Trusted entrypoint for one untrusted candidate solve inside a networkless container."""

from __future__ import annotations

import importlib.util
import json
import selectors
import socket
import socketserver
import sys
import threading

_RESULT_MARKER = "VANGUARSTEW_SANDBOX_RESULT="
_SOCKET_PATH = "/broker/model.sock"


class _Relay(socketserver.BaseRequestHandler):
    def handle(self):
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(_SOCKET_PATH)
        selector = selectors.DefaultSelector()
        try:
            selector.register(self.request, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, self.request)
            while selector.get_map():
                for key, _ in selector.select(timeout=10):
                    data = key.fileobj.recv(65536)
                    if not data:
                        return
                    key.data.sendall(data)
        finally:
            selector.close()
            upstream.close()


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _load_solve():
    spec = importlib.util.spec_from_file_location("candidate_entry", "/candidate/agent.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("candidate entrypoint is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    solve = getattr(module, "solve", None)
    if not callable(solve):
        raise RuntimeError("candidate solve entrypoint is unavailable")
    return solve


def main() -> int:
    with open("/input/request.json", "r", encoding="utf-8") as handle:
        request = json.load(handle)
    server = _Server(("127.0.0.1", 18080), _Relay)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = _load_solve()(
            repo_path="/workspace",
            request=request["request"],
            model=request["model"],
            api_base="http://127.0.0.1:18080",
            api_key="sandbox-broker",
            n=request["n"],
        )
        if not isinstance(result, dict):
            result = {}
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        sys.stdout.write(_RESULT_MARKER + encoded + "\n")
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
