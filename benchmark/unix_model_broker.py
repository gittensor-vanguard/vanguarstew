"""Fixed-upstream OpenAI-compatible model broker exposed through a Unix socket."""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import threading
import urllib.request

MAX_BROKER_REQUEST_BYTES = 1024 * 1024
MAX_BROKER_RESPONSE_BYTES = 2 * 1024 * 1024


class ModelBrokerError(RuntimeError):
    """The bounded fixed-upstream broker could not be started or used."""


class _UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


class UnixModelBroker:
    """Context manager that keeps the real API key outside an untrusted container."""

    def __init__(self, *, socket_path, api_base, api_key, model, max_calls=24, timeout=90,
                 opener=urllib.request.urlopen):
        self.socket_path = os.path.realpath(os.fspath(socket_path))
        if os.path.lexists(self.socket_path):
            raise ModelBrokerError("broker socket path already exists")
        if not isinstance(api_base, str) or not api_base.startswith("https://"):
            raise ModelBrokerError("broker upstream must use HTTPS")
        if not all(isinstance(value, str) and value for value in (api_key, model)):
            raise ModelBrokerError("broker key and model are required")
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_calls = max_calls
        self.timeout = timeout
        self.opener = opener
        self.calls = 0
        self._lock = threading.Lock()
        self._server = None
        self._thread = None

    def _handler(self):
        broker = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                try:
                    if self.path != "/chat/completions":
                        raise ModelBrokerError("unsupported route")
                    length = int(self.headers.get("Content-Length", "-1"))
                    if not 0 < length <= MAX_BROKER_REQUEST_BYTES:
                        raise ModelBrokerError("request size is invalid")
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict) or not isinstance(body.get("messages"), list):
                        raise ModelBrokerError("request shape is invalid")
                    with broker._lock:
                        if broker.calls >= broker.max_calls:
                            raise ModelBrokerError("model call budget exhausted")
                        broker.calls += 1
                    body["model"] = broker.model
                    body["max_tokens"] = max(1, min(int(body.get("max_tokens", 4096)), 4096))
                    request = urllib.request.Request(
                        broker.api_base + "/chat/completions",
                        data=json.dumps(body, allow_nan=False).encode("utf-8"),
                        headers={
                            "Authorization": "Bearer " + broker.api_key,
                            "Content-Type": "application/json",
                        },
                        method="POST",
                    )
                    with broker.opener(request, timeout=broker.timeout) as response:
                        payload = response.read(MAX_BROKER_RESPONSE_BYTES + 1)
                    if len(payload) > MAX_BROKER_RESPONSE_BYTES:
                        raise ModelBrokerError("upstream response exceeds the size limit")
                    json.loads(payload)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    payload = b'{"error":{"message":"model broker request failed"}}'
                    self.send_response(502)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)

        return Handler

    def __enter__(self):
        self._server = _UnixHTTPServer(self.socket_path, self._handler())
        os.chmod(self.socket_path, 0o666)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *args):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        self.api_key = ""
