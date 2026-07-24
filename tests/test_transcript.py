"""Tests for benchmark/transcript.py + benchmark/attestation.py -- the reproducibility and
attestation-binding layer (TEE track, Phase 0).

The property under test throughout: a recorded run can be replayed byte-identically, and a score
cannot be silently edited after the fact without breaking its binding.
"""

import json
import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.attestation import build_evidence, verify_evidence  # noqa: E402
from benchmark.transcript import (  # noqa: E402
    TranscriptStore,
    canonical_json,
    digest,
    request_key,
)

_REQ = {"model": "m", "temperature": 0,
        "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]}


# --- canonical form / keying ----------------------------------------------------------------

def test_canonical_json_is_stable_across_dict_order():
    a = {"b": 1, "a": {"y": 2, "x": 3}}
    b = {"a": {"x": 3, "y": 2}, "b": 1}
    assert canonical_json(a) == canonical_json(b)
    assert digest(a) == digest(b)


def test_request_key_ignores_transport_only_fields():
    # stream/user/n don't change which answer is correct to replay, so they must not shift the key
    # (otherwise a caller refactor silently invalidates every recorded transcript).
    assert request_key(_REQ) == request_key({**_REQ, "stream": True, "user": "x", "n": 1})


def test_request_key_changes_with_meaning():
    assert request_key(_REQ) != request_key({**_REQ, "model": "other"})
    assert request_key(_REQ) != request_key({**_REQ, "temperature": 1})
    assert request_key(_REQ) != request_key(
        {**_REQ, "messages": [{"role": "user", "content": "different"}]})


def test_request_key_tolerates_a_non_dict_request():
    for bad in ("x", 5, None, [1]):
        assert isinstance(request_key(bad), str) and len(request_key(bad)) == 64


# --- record / replay ------------------------------------------------------------------------

def test_replay_returns_recorded_response():
    store = TranscriptStore()
    store.record(_REQ, "answer")
    assert store.replay(_REQ) == "answer"


def test_repeated_prompt_replays_in_recorded_order():
    # The dual-order judge asks about the same pair twice; replay must reproduce the original
    # SEQUENCE, not just the set of answers.
    store = TranscriptStore()
    store.record(_REQ, "first")
    store.record(_REQ, "second")
    assert [store.replay(_REQ), store.replay(_REQ)] == ["first", "second"]


def test_replay_past_the_recording_is_a_miss_not_a_wrong_answer():
    # A run that makes MORE calls than were recorded has diverged from the recorded run. Serving a
    # stale answer would corrupt the artifact; None lets the caller fail loudly.
    store = TranscriptStore()
    store.record(_REQ, "only")
    store.replay(_REQ)
    assert store.replay(_REQ) is None


def test_reset_rewinds_cursors_for_a_second_run():
    store = TranscriptStore()
    store.record(_REQ, "first")
    assert store.replay(_REQ) == "first"
    store.reset()
    assert store.replay(_REQ) == "first"


def test_unrecorded_request_misses():
    store = TranscriptStore()
    store.record(_REQ, "answer")
    assert store.replay({**_REQ, "messages": [{"role": "user", "content": "unseen"}]}) is None


# --- persistence ----------------------------------------------------------------------------

def test_round_trip_through_disk_preserves_replay(tmp_path):
    store = TranscriptStore()
    store.record(_REQ, "answer")
    path = str(tmp_path / "t.json")
    store.save(path)
    assert TranscriptStore.load(path).replay(_REQ) == "answer"


def test_digest_is_stable_and_content_sensitive(tmp_path):
    a, b = TranscriptStore(), TranscriptStore()
    a.record(_REQ, "answer")
    b.record(_REQ, "answer")
    assert a.digest() == b.digest()
    b.record(_REQ, "extra")
    assert a.digest() != b.digest()


def test_from_dict_tolerates_malformed_files():
    for bad in ("nope", 5, None, [1], {"entries": "nope"}, {"entries": 5}, {}):
        assert len(TranscriptStore.from_dict(bad)) == 0
    # non-dict rows inside a valid list are dropped, valid ones survive
    store = TranscriptStore.from_dict({"entries": [None, "x", {"key": "k", "response": "r"}]})
    assert len(store) == 1


# --- attestation binding --------------------------------------------------------------------

_INPUTS = {"repo_set": "curated", "seed": 0, "model": "m@snap1", "agent_commit": "abc",
           "eval_image": "sha256:img", "transcript_digest": "t123"}
_ARTIFACT = {"composite_mean": 0.62, "composite_parts": {"judge_mean": 0.6}}


def test_evidence_verifies_against_its_own_artifact():
    evidence = build_evidence(_ARTIFACT, _INPUTS)
    report = verify_evidence(_ARTIFACT, evidence)
    assert report["ok"] is True
    assert report["quote_checked"] is False  # honest: no hardware attestation took part


def test_editing_the_published_score_breaks_the_binding():
    evidence = build_evidence(_ARTIFACT, _INPUTS)
    report = verify_evidence({**_ARTIFACT, "composite_mean": 0.99}, evidence)
    assert report["ok"] is False
    assert report["checks"]["artifact_digest"] is False


def test_claiming_different_inputs_breaks_the_binding():
    # A score is only meaningful relative to what produced it -- swapping in an easier repo set
    # must not verify against the same report_data.
    evidence = build_evidence(_ARTIFACT, _INPUTS)
    evidence["inputs"] = {**evidence["inputs"], "repo_set": "easy"}
    assert verify_evidence(_ARTIFACT, evidence)["ok"] is False


def test_quote_binding_checked_only_when_a_quote_is_supplied():
    evidence = build_evidence(_ARTIFACT, _INPUTS)
    matching = verify_evidence(_ARTIFACT, evidence, evidence["report_data"])
    assert matching["checks"]["quote_binding"] is True and matching["quote_checked"] is True
    wrong = verify_evidence(_ARTIFACT, evidence, "0" * 64)
    assert wrong["checks"]["quote_binding"] is False and wrong["ok"] is False


def test_verify_evidence_tolerates_a_non_dict_evidence():
    for bad in ("x", 5, None, [1]):
        assert verify_evidence(_ARTIFACT, bad)["ok"] is False


def test_unknown_input_keys_do_not_change_the_binding():
    # A caller may pass a richer run-description; only the bound fields may affect report_data.
    base = build_evidence(_ARTIFACT, _INPUTS)
    richer = build_evidence(_ARTIFACT, {**_INPUTS, "operator_note": "anything"})
    assert base["report_data"] == richer["report_data"]


# --- proxy end-to-end -----------------------------------------------------------------------

def test_replay_proxy_serves_recorded_answers_to_the_real_llm_client():
    """The whole point: the UNMODIFIED agent LLM client, pointed at the proxy, replays offline.

    Interception happens at the HTTP layer precisely so `agent/` -- the contributor-editable
    surface the benchmark scores -- needs no change to make a run reproducible.
    """
    from agent.llm import LLM
    from scripts.transcript_proxy import build_server

    store = TranscriptStore()
    # what agent/llm.py actually sends for chat(system="sys", user="hello")
    store.record({"model": "m", "temperature": 0,
                  "messages": [{"role": "system", "content": "sys"},
                               {"role": "user", "content": "hello"}]},
                 '{"answer": 42}')

    server = build_server("replay", 0, store=store)  # port 0 -> OS-assigned, no collisions
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        llm = LLM(model="m", api_base=f"http://127.0.0.1:{port}/v1", api_key="k")
        llm.offline = False  # force the live HTTP path so the proxy is genuinely exercised
        assert llm.chat_json("sys", "hello", stub={"fallback": True}) == {"answer": 42}
    finally:
        server.shutdown()
        server.server_close()


def test_replay_proxy_rejects_an_uncovered_request_rather_than_inventing_one():
    """A transcript miss must surface as an error, never as a plausible-but-wrong answer -- a
    silent fallback would produce a corrupt artifact that still looks valid."""
    import urllib.error
    import urllib.request

    from scripts.transcript_proxy import build_server

    server = build_server("replay", 0, store=TranscriptStore())
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/chat/completions",
            data=json.dumps(_REQ).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("expected an error for an uncovered request")
        except urllib.error.HTTPError as exc:
            assert exc.code == 409
    finally:
        server.shutdown()
        server.server_close()


def test_build_server_binds_the_exact_store_even_when_empty():
    """Regression: an empty TranscriptStore is falsy (defines __len__), so `store or ...` in
    build_server bound a throwaway store while the caller saved the original -- record mode, which
    always starts empty, then recorded into one object and persisted another (recorded nothing).
    build_server must bind the *exact* store it was handed."""
    from scripts.transcript_proxy import build_server
    empty = TranscriptStore()
    assert len(empty) == 0 and not empty  # empty store really is falsy -- that's the trap
    server = build_server("record", 0, upstream="http://unused", store=empty)
    try:
        assert server.RequestHandlerClass.store is empty
    finally:
        server.server_close()


def test_record_mode_actually_records_through_a_fake_upstream():
    """End-to-end record path (missing from the earlier replay-only tests): a call THROUGH the
    proxy in record mode must land in the transcript the caller saves."""
    import urllib.request

    from scripts.transcript_proxy import build_server

    # a stand-in upstream that returns a canned completion
    upstream_store = TranscriptStore()
    upstream_store.record(
        {"model": "m", "temperature": 0, "messages": [{"role": "user", "content": "hi"}]},
        "upstream-answer")
    upstream = build_server("replay", 0, store=upstream_store)
    up_port = upstream.server_address[1]
    threading.Thread(target=upstream.serve_forever, daemon=True).start()

    store = TranscriptStore()  # empty, as record mode always is
    recorder = build_server("record", 0, upstream=f"http://127.0.0.1:{up_port}", store=store)
    rec_port = recorder.server_address[1]
    threading.Thread(target=recorder.serve_forever, daemon=True).start()
    try:
        body = json.dumps({"model": "m", "temperature": 0,
                           "messages": [{"role": "user", "content": "hi"}]}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{rec_port}/v1/chat/completions",
                                     data=body, headers={"Content-Type": "application/json"},
                                     method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            got = json.loads(resp.read())
        assert got["choices"][0]["message"]["content"] == "upstream-answer"
        # the recording landed in the SAME store object the caller holds
        assert len(store) == 1
        assert store.replay({"model": "m", "temperature": 0,
                             "messages": [{"role": "user", "content": "hi"}]}) == "upstream-answer"
    finally:
        recorder.shutdown()
        recorder.server_close()
        upstream.shutdown()
        upstream.server_close()
