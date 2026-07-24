"""Spec 080 contract tests for benchmark/transcript.py (the run transcript).

Pins the as-built behavior described in specs/080-benchmark-transcript/spec.md with literal
expected values -- exact canonical serializations and exact sha256 hexes -- so a change to the
canonical form fails loudly instead of silently agreeing with itself. Broader behavioral coverage
(the replay proxy, the attestation binding) lives in tests/test_transcript.py.
"""

import json
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.transcript import (  # noqa: E402
    _KEYED_REQUEST_FIELDS,
    TRANSCRIPT_VERSION,
    TranscriptStore,
    canonical_json,
    digest,
    request_key,
)

LOGGER = "benchmark.transcript"

REQ = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0}

# Pinned literals from the as-built canonical form (see spec.md § Digest primitive).
DIGEST_EMPTY_DICT = "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
DIGEST_NONE = "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"


def _store(*pairs):
    """A store built through the public recording path."""
    store = TranscriptStore()
    for request, response in pairs:
        store.record(request, response)
    return store


def _warnings(caplog):
    return [r.message for r in caplog.records if r.name == LOGGER]


# --- Constants -----------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert TRANSCRIPT_VERSION == 1
    assert _KEYED_REQUEST_FIELDS == ("model", "messages", "temperature")


# --- Canonical serialization ---------------------------------------------------------------------

def test_canonical_json_sorts_keys_and_drops_whitespace():
    # Sorted keys, not insertion order -- the whole point is that a dict built two ways serializes
    # identically -- and no incidental separator whitespace.
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'
    assert canonical_json({"a": 2, "b": 1}) == '{"a":2,"b":1}'
    assert canonical_json([1, {"x": 2}]) == '[1,{"x":2}]'


def test_canonical_json_escapes_non_ascii():
    assert canonical_json({"k": "café"}) == '{"k":"caf\\u00e9"}'


def test_canonical_json_stringifies_an_unserializable_value():
    # default=str: a value json cannot encode is stringified rather than raising.
    class Fixed:
        def __str__(self):
            return "fixed"

    assert canonical_json({"v": Fixed()}) == '{"v":"fixed"}'


def test_canonical_json_collapses_distinct_objects_with_equal_str():
    # Where the stability guarantee stops, part 1: two DISTINCT objects whose str() agree are
    # indistinguishable after serialization, so they share a request_key and a digest.
    class Fixed:
        def __str__(self):
            return "same"

    left, right = Fixed(), Fixed()
    assert left is not right
    assert canonical_json(left) == canonical_json(right) == '"same"'
    assert digest(left) == digest(right)
    assert request_key({"model": left, "messages": []}) == request_key({"model": right,
                                                                        "messages": []})


def test_canonical_json_is_not_process_stable_for_identity_bearing_str():
    # Where the stability guarantee stops, part 2: str(object()) embeds a process-local address, so
    # the serialization is neither equal across instances nor reproducible across processes. A
    # caller that needs a stable digest must pass JSON-representable values.
    first, second = object(), object()
    assert canonical_json(first) != canonical_json(second)
    assert canonical_json(first).startswith('"<object object at 0x')
    assert digest(first) != digest(second)


# --- Digest primitive ----------------------------------------------------------------------------

def test_digest_pins_literal_hexes():
    assert digest({}) == DIGEST_EMPTY_DICT
    assert digest(None) == DIGEST_NONE


def test_digest_ignores_dict_insertion_order():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})


# --- Replay key ----------------------------------------------------------------------------------

def test_request_key_is_the_digest_of_the_keyed_fields_only():
    assert request_key(REQ) == digest({f: REQ.get(f) for f in _KEYED_REQUEST_FIELDS})


def test_request_key_ignores_transport_fields():
    noisy = dict(REQ, stream=True, user="someone", n=3)
    assert request_key(noisy) == request_key(REQ)


def test_request_key_changes_with_each_keyed_field():
    assert request_key(dict(REQ, model="other")) != request_key(REQ)
    assert request_key(dict(REQ, temperature=0.1)) != request_key(REQ)
    assert request_key(dict(REQ, messages=[{"role": "user", "content": "bye"}])) != request_key(REQ)


def test_request_key_treats_an_absent_keyed_field_as_none():
    # `.get` defaults to None, so "temperature omitted" and "temperature: null" are one key.
    assert request_key({"model": "m", "messages": []}) == request_key(
        {"model": "m", "messages": [], "temperature": None})


def test_request_key_warns_and_keys_verbatim_for_a_non_dict(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert request_key([1, 2]) == digest([1, 2])
    assert any("request is list, not a dict" in m for m in _warnings(caplog))


# --- Construction --------------------------------------------------------------------------------

def test_init_coerces_falsy_entries_to_empty():
    assert len(TranscriptStore()) == 0
    assert len(TranscriptStore(None)) == 0
    assert len(TranscriptStore([])) == 0
    assert len(TranscriptStore(0)) == 0


def test_init_is_not_the_tolerant_path():
    # from_dict is the entry point for untrusted data; the constructor assumes an iterable.
    with pytest.raises(TypeError):
        TranscriptStore(5)


# --- Recording -----------------------------------------------------------------------------------

def test_record_appends_the_documented_row_shape():
    store = TranscriptStore()
    assert store.record(REQ, "answer") is None
    (entry,) = store.to_dict()["entries"]
    assert sorted(entry) == ["key", "request", "response"]
    assert entry == {"key": request_key(REQ), "request": REQ, "response": "answer"}


def test_record_stores_the_caller_object_so_a_later_mutation_desyncs_the_key():
    # The stored body is the caller's object, not a copy: mutating it after recording rewrites the
    # body while `key` stays computed from the value at record time.
    request = {"model": "m", "messages": [{"role": "user", "content": "before"}]}
    store = TranscriptStore()
    store.record(request, "answer")
    (entry,) = store.to_dict()["entries"]
    recorded_key = entry["key"]

    request["messages"][0]["content"] = "after"

    assert entry["request"]["messages"][0]["content"] == "after"
    assert request_key(entry["request"]) != recorded_key


def test_record_drops_a_non_dict_request_body_but_keeps_its_key(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        store = _store((["not", "a", "dict"], "answer"))
    (entry,) = store.to_dict()["entries"]
    assert entry["request"] is None
    assert entry["key"] == digest(["not", "a", "dict"])
    # ... so this entry's key is not recomputable from the stored body either.
    assert request_key(entry["request"]) != entry["key"]


# --- Ordered replay ------------------------------------------------------------------------------

def test_replay_serves_repeated_requests_in_recorded_order():
    # The dual-order judge asks the same pair twice; both original answers must come back, in
    # sequence -- reproducing the original run, not merely its set of answers.
    store = _store((REQ, "first"), (REQ, "second"))
    assert store.replay(REQ) == "first"
    assert store.replay(REQ) == "second"


def test_unmatched_request_misses_silently(caplog):
    store = _store((REQ, "answer"))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert store.replay({"model": "unrecorded", "messages": []}) is None
    assert _warnings(caplog) == []


def test_exhausted_key_warns_and_misses(caplog):
    store = _store((REQ, "only"))
    assert store.replay(REQ) == "only"
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert store.replay(REQ) is None
    assert any("exhausted 1 recorded response(s) for key" in m for m in _warnings(caplog))
    assert any(request_key(REQ)[:12] in m for m in _warnings(caplog))


def test_row_without_a_response_replays_none():
    store = TranscriptStore.from_dict({"entries": [{"key": request_key(REQ)}]})
    assert store.replay(REQ) is None


def test_row_without_a_key_never_matches():
    # A None key cannot equal a hex digest, so the row is unreachable for every request.
    store = TranscriptStore.from_dict({"entries": [{"response": "orphan"}]})
    assert store.replay(REQ) is None
    assert store.replay({}) is None
    assert len(store) == 1


def test_reset_rewinds_cursors_without_touching_entries():
    store = _store((REQ, "first"), (REQ, "second"))
    assert [store.replay(REQ), store.replay(REQ)] == ["first", "second"]
    before = store.to_dict()
    store.reset()
    assert [store.replay(REQ), store.replay(REQ)] == ["first", "second"]
    assert store.to_dict() == before


# --- Size and serialization ----------------------------------------------------------------------

def test_len_counts_unreplayable_entries():
    store = TranscriptStore.from_dict(
        {"entries": [{"key": request_key(REQ), "response": "real"}, {}]})
    assert len(store) == 2


def test_to_dict_shape_is_pinned():
    store = _store((REQ, "answer"))
    payload = store.to_dict()
    assert sorted(payload) == ["entries", "version"]
    assert payload["version"] == TRANSCRIPT_VERSION
    assert payload["entries"] == [{"key": request_key(REQ), "request": REQ, "response": "answer"}]


def test_save_writes_readable_json_and_load_round_trips(tmp_path):
    path = str(tmp_path / "transcript.json")
    _store((REQ, "first"), (REQ, "second")).save(path)

    raw = open(path, encoding="utf-8").read()
    # Deliberately the readable form (indent=1, sort_keys=True), not the canonical_json form.
    assert raw == json.dumps(
        {"version": TRANSCRIPT_VERSION,
         "entries": [{"key": request_key(REQ), "request": REQ, "response": "first"},
                     {"key": request_key(REQ), "request": REQ, "response": "second"}]},
        indent=1, sort_keys=True)

    reloaded = TranscriptStore.load(path)
    assert [reloaded.replay(REQ), reloaded.replay(REQ)] == ["first", "second"]


# --- Tolerant load -------------------------------------------------------------------------------

def test_from_dict_warns_on_a_non_dict_file(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        store = TranscriptStore.from_dict(["not", "a", "dict"])
    assert len(store) == 0
    assert any("file is list, not a dict" in m for m in _warnings(caplog))


def test_from_dict_warns_on_non_list_entries(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        store = TranscriptStore.from_dict({"entries": "nope"})
    assert len(store) == 0
    assert any("entries is str, not a list" in m for m in _warnings(caplog))


def test_from_dict_is_silent_when_entries_is_absent_or_none(caplog):
    # The absent/None case is deliberately quiet -- assert the silence, or a future warning here
    # would slip in untested.
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert len(TranscriptStore.from_dict({"version": 1})) == 0
        assert len(TranscriptStore.from_dict({"entries": None})) == 0
    assert _warnings(caplog) == []


def test_from_dict_drops_non_dict_rows_without_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        store = TranscriptStore.from_dict(
            {"entries": [{"key": request_key(REQ), "response": "kept"}, "junk", 5, None]})
    assert len(store) == 1
    assert store.replay(REQ) == "kept"
    assert _warnings(caplog) == []


def test_from_dict_keeps_a_contentless_row():
    # Row *contents* are not validated: {} is kept, is permanently unreplayable, and still counts.
    store = TranscriptStore.from_dict({"entries": [{}]})
    assert len(store) == 1
    assert store.replay(REQ) is None


def test_from_dict_ignores_the_declared_version():
    # version is written by to_dict and never read by from_dict: a newer-version transcript loads
    # as if it were TRANSCRIPT_VERSION, and is re-stamped on the next save.
    store = TranscriptStore.from_dict(
        {"version": 99, "entries": [{"key": request_key(REQ), "response": "kept"}]})
    assert len(store) == 1
    assert store.replay(REQ) == "kept"
    assert store.to_dict()["version"] == TRANSCRIPT_VERSION


# --- Transcript identity -------------------------------------------------------------------------

def test_store_digest_is_keys_and_responses_only():
    store = _store((REQ, "first"), (REQ, "second"))
    key = request_key(REQ)
    assert store.digest() == digest([[key, "first"], [key, "second"]])


def test_store_digest_ignores_a_cosmetic_request_body_change():
    # Stored bodies are derived data kept for auditability; hashing them would shift the identity
    # on a request-shape change that did not alter a single answer.
    recorded = _store((REQ, "answer"))
    same_key_other_body = TranscriptStore.from_dict(
        {"entries": [{"key": request_key(REQ), "request": {"anything": "else"},
                      "response": "answer"}]})
    assert recorded.digest() == same_key_other_body.digest()


def test_store_digest_changes_with_recorded_order():
    assert _store((REQ, "a"), (REQ, "b")).digest() != _store((REQ, "b"), (REQ, "a")).digest()


def test_store_digest_changes_with_an_unreplayable_row():
    # A {} row contributes [None, None], so the declared identity moves even though the row cannot
    # influence a single replayed answer.
    clean = TranscriptStore.from_dict({"entries": [{"key": request_key(REQ), "response": "a"}]})
    padded = TranscriptStore.from_dict(
        {"entries": [{"key": request_key(REQ), "response": "a"}, {}]})
    assert clean.digest() != padded.digest()
    assert padded.digest() == digest([[request_key(REQ), "a"], [None, None]])


# --- Pure evaluation -----------------------------------------------------------------------------

def test_replay_does_not_mutate_entries_or_request():
    store = _store((REQ, "answer"))
    entries_before = store.to_dict()
    request = dict(REQ)
    assert store.replay(request) == "answer"
    assert request == REQ
    assert store.to_dict() == entries_before
