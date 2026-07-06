"""Contract tests for specs/008-agent-philosophy — assert philosophy.py satisfies the spec's
EARS criteria: philosophy dict shape, text/list field normalization, few-shot prompt contract,
offline determinism, and non-dict LLM output fallback. Offline, deterministic; LLMs are
scripted fakes so no network is used.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.philosophy import (  # noqa: E402
    FEWSHOT,
    _normalize_philosophy,
    _normalize_string_list,
    _normalize_text,
    infer_philosophy,
)

_PHILOSOPHY_KEYS = frozenset({
    "summary", "values", "merge_bar", "direction", "evidence",
})

_STUB = {
    "summary": "offline stub philosophy",
    "values": [],
    "merge_bar": "unknown (offline)",
    "direction": "unknown (offline)",
    "evidence": [],
}


class _FakeLLM:
    """Return a fixed JSON object from chat_json."""

    offline = False

    def __init__(self, payload):
        self.payload = payload

    def chat_json(self, system, user, stub=None):
        return self.payload


def _assert_full_philosophy_shape(out: dict):
    assert isinstance(out, dict)
    assert _PHILOSOPHY_KEYS <= set(out)
    assert isinstance(out["summary"], str)
    assert isinstance(out["values"], list)
    assert all(isinstance(v, str) for v in out["values"])
    assert isinstance(out["merge_bar"], str)
    assert isinstance(out["direction"], str)
    assert isinstance(out["evidence"], list)
    assert all(isinstance(e, str) for e in out["evidence"])


def _fewshot_outputs():
    outs = []
    for chunk in FEWSHOT.split("OUTPUT:\n")[1:]:
        outs.append(json.loads(chunk.splitlines()[0]))
    return outs


# --- Philosophy dict shape ------------------------------------------------------------------

def test_infer_philosophy_returns_all_documented_keys_offline():
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, LLM(api_key="offline"))
    _assert_full_philosophy_shape(out)


def test_infer_philosophy_falls_back_when_llm_returns_non_dict():
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _FakeLLM(["not", "a", "dict"]))
    _assert_full_philosophy_shape(out)
    assert out["summary"] == "offline stub philosophy"


def test_infer_philosophy_normalizes_every_field_from_a_rich_llm_payload():
    payload = {
        "summary": "A conservative library.",
        "values": "stability-over-features",
        "merge_bar": "High bar for new deps.",
        "direction": 99,
        "evidence": "recent refactors",
        "extra_noise": "ignored",
    }
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _FakeLLM(payload))
    _assert_full_philosophy_shape(out)
    assert out["summary"] == "A conservative library."
    assert out["values"] == ["stability-over-features"]
    assert out["merge_bar"] == "High bar for new deps."
    assert out["direction"] == "99"
    assert out["evidence"] == ["recent refactors"]


@pytest.mark.parametrize("bad_context", [None, 42, "not a dict", []])
def test_non_dict_context_returns_minimal_fallback_without_llm(bad_context):
    out = infer_philosophy(bad_context, _FakeLLM({"summary": "should not appear"}))
    assert out == {"summary": "offline stub philosophy", "values": ["triage"]}


# --- Text field normalization ---------------------------------------------------------------

@pytest.mark.parametrize("raw,default,expected", [
    (None, "fallback", "fallback"),
    ("ship fixes", "fallback", "ship fixes"),
    (42, "fallback", "42"),
    ("  trim me  ", "fallback", "  trim me  "),
])
def test_text_fields_coerce_to_string(raw, default, expected):
    assert _normalize_text(raw, default) == expected


def test_null_summary_uses_stub_default():
    out = _normalize_philosophy({"summary": None}, _STUB)
    assert out["summary"] == _STUB["summary"]


def test_null_direction_uses_stub_default():
    out = _normalize_philosophy({"direction": None}, _STUB)
    assert out["direction"] == _STUB["direction"]


# --- List field normalization ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (None, []),
    ("", []),
    ("  ", []),
    ("conservative", ["conservative"]),
    ("  feature-first  ", ["feature-first"]),
    (["a", "", None, "  b  ", 7], ["a", "b", "7"]),
    (42, []),
    ({"bad": True}, []),
    ([], []),
])
def test_string_list_fields_coerce_to_string_list(raw, expected):
    assert _normalize_string_list(raw) == expected


def test_values_and_evidence_are_independent():
    out = _normalize_philosophy({
        "values": "conservative",
        "evidence": None,
    }, _STUB)
    assert out["values"] == ["conservative"]
    assert out["evidence"] == []


# --- Few-shot prompt contract ---------------------------------------------------------------

def test_fewshot_includes_at_least_one_valid_example():
    outputs = _fewshot_outputs()
    assert len(outputs) >= 1
    for ex in outputs:
        assert _PHILOSOPHY_KEYS <= set(ex)
        assert isinstance(ex["values"], list) and ex["values"]
        assert isinstance(ex["evidence"], list) and ex["evidence"]
        assert isinstance(ex["summary"], str) and ex["summary"]


def test_fewshot_examples_have_non_empty_merge_bar_and_direction():
    for ex in _fewshot_outputs():
        assert isinstance(ex["merge_bar"], str) and ex["merge_bar"]
        assert isinstance(ex["direction"], str) and ex["direction"]


# --- Offline determinism --------------------------------------------------------------------

def test_offline_infer_philosophy_is_deterministic():
    ctx = {"recent_commits": [{"subject": "Fix crash in parser"}]}
    llm = LLM(api_key="offline")
    first = infer_philosophy(ctx, llm)
    second = infer_philosophy(ctx, llm)
    _assert_full_philosophy_shape(first)
    assert first == second
    assert first["summary"] == "offline stub philosophy"
    assert first["merge_bar"] == "unknown (offline)"


# --- Robustness: malformed structured fields together ---------------------------------------

def test_normalize_philosophy_coerces_all_malformed_fields_without_crashing():
    payload = {
        "summary": None,
        "values": 123,
        "merge_bar": ["not", "a", "string"],
        "direction": True,
        "evidence": {"signal": "bad"},
    }
    out = _normalize_philosophy(payload, _STUB)
    _assert_full_philosophy_shape(out)
    assert out == {
        "summary": "offline stub philosophy",
        "values": [],
        "merge_bar": "['not', 'a', 'string']",
        "direction": "True",
        "evidence": [],
    }


def test_infer_philosophy_end_to_end_malformed_llm_payload():
    payload = {
        "summary": None,
        "values": "feature-first",
        "merge_bar": 123,
        "direction": None,
        "evidence": None,
    }
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _FakeLLM(payload))
    _assert_full_philosophy_shape(out)
    assert out["summary"] == "offline stub philosophy"
    assert out["values"] == ["feature-first"]
    assert out["merge_bar"] == "123"
    assert out["direction"] == "unknown (offline)"
    assert out["evidence"] == []


def test_bad_summary_does_not_block_other_field_normalization():
    payload = {
        "summary": ["broken"],
        "values": ["conservative", "docs-first"],
        "merge_bar": "strict",
        "direction": "harden core",
        "evidence": ["deprecation shims"],
    }
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _FakeLLM(payload))
    _assert_full_philosophy_shape(out)
    assert out["summary"] == "['broken']"
    assert out["values"] == ["conservative", "docs-first"]
    assert out["evidence"] == ["deprecation shims"]
