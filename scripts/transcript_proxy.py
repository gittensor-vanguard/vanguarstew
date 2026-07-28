"""A record/replay proxy for the managed-inference endpoint, so a benchmark run is reproducible.

  # 1. record a real run's model calls
  python -m scripts.transcript_proxy --mode record --upstream https://api.example/v1 \
      --out transcript.json --port 8712
  python -m scripts.run_eval --repo ... --api-base http://127.0.0.1:8712/v1 --api-key "$KEY" ...

  # 2. replay it later, offline, byte-identically
  python -m scripts.transcript_proxy --mode replay --transcript transcript.json --port 8712
  python -m scripts.run_eval --repo ... --api-base http://127.0.0.1:8712/v1 --api-key offline ...

Why a *proxy* rather than wrapping the LLM client: a replay run makes model calls from two
independent places — the agent builds its own client inside ``solve()`` from the ``api_base`` it is
handed, and the judge builds a separate one in the runner. Intercepting at the HTTP layer catches
both, and needs no change to ``agent/`` — the contributor-editable surface the benchmark scores.
It is also exactly the shape this takes inside a TEE, where the enclave runs the proxy and the
transcript becomes the evidence of what the model was asked and answered.

Auth is never stored here: record mode forwards the caller's own ``Authorization`` header upstream,
so the proxy handles no credentials of its own.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from benchmark.transcript import TranscriptStore

# Both spellings the OpenAI-compatible clients in this repo may produce, depending on whether the
# caller's api_base already ends in /v1.
_COMPLETION_PATHS = ("/chat/completions", "/v1/chat/completions")

MAX_BODY_BYTES = 32 * 1024 * 1024


def _completion_envelope(content: str) -> dict:
    """The minimal chat-completion response shape ``agent/llm.py`` reads on replay."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class _Handler(BaseHTTPRequestHandler):
    mode = "replay"
    upstream = ""
    store: TranscriptStore = None  # set on the class before serving

    def log_message(self, fmt, *args):  # keep the eval's stdout readable
        pass

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler's required spelling)
        if not any(self.path.endswith(p) for p in _COMPLETION_PATHS):
            self._send_json(404, {"error": f"unsupported path {self.path}"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY_BYTES:
            self._send_json(413, {"error": "request too large"})
            return
        try:
            request = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": f"unparseable request body: {exc}"})
            return

        if self.mode == "replay":
            content = self.store.replay(request)
            if content is None:
                # Fail loudly: a miss means the replayed run diverged from the recorded one, and
                # silently inventing an answer would corrupt the very reproducibility this exists
                # to provide.
                self._send_json(409, {"error": "no recorded response for this request"})
                return
            self._send_json(200, _completion_envelope(content))
            return

        # record mode -- forward verbatim, capture the assistant content, store it
        try:
            content, raw = self._forward(request)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self._send_json(502, {"error": f"upstream call failed: {exc}"})
            return
        self.store.record(request, content)
        self._send_json(200, raw)

    def _forward(self, request: dict):
        """POST ``request`` upstream and return ``(assistant_content, raw_response_body)``."""
        req = urllib.request.Request(
            f"{self.upstream.rstrip('/')}/chat/completions",
            data=json.dumps(request).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                # forwarded, never stored: the proxy holds no credentials of its own
                "Authorization": self.headers.get("Authorization", ""),
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        return raw["choices"][0]["message"]["content"], raw


def build_server(mode: str, port: int, upstream: str = "", store: TranscriptStore = None):
    # `store if store is not None`, NOT `store or ...`: a TranscriptStore defines __len__, so an
    # EMPTY one is falsy -- and record mode always starts empty. `store or TranscriptStore()` would
    # therefore bind a throwaway store to the handler while main() saved the original, so record
    # mode recorded into one object and persisted another (i.e. never recorded anything).
    handler = type("_BoundHandler", (_Handler,), {
        "mode": mode, "upstream": upstream,
        "store": store if store is not None else TranscriptStore(),
    })
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("record", "replay"), required=True)
    ap.add_argument("--port", type=int, default=8712)
    ap.add_argument("--upstream", default="", help="real api_base (record mode)")
    ap.add_argument("--transcript", default="", help="transcript to replay (replay mode)")
    ap.add_argument("--out", default="transcript.json", help="where to write (record mode)")
    args = ap.parse_args(argv)

    if args.mode == "record" and not args.upstream:
        ap.error("--upstream is required in record mode")
    if args.mode == "replay" and not args.transcript:
        ap.error("--transcript is required in replay mode")

    store = TranscriptStore.load(args.transcript) if args.mode == "replay" else TranscriptStore()
    server = build_server(args.mode, args.port, args.upstream, store)
    print(f"transcript_proxy: {args.mode} on http://127.0.0.1:{args.port}/v1 "
          f"({len(store)} recorded call(s))", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args.mode == "record":
            store.save(args.out)
            print(f"transcript_proxy: wrote {len(store)} call(s) to {args.out} "
                  f"(digest {store.digest()[:12]})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
