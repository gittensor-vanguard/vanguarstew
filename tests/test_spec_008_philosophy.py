"""Spec 008 contract tests for agent/philosophy.py (maintainer-philosophy inference).

Pins the as-built behavior described in specs/008-agent-philosophy/spec.md with literal expected
values, so a change in the normalizers fails loudly instead of silently agreeing with itself.
Broader behavioral coverage lives in tests/test_philosophy.py.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm import LLM  # noqa: E402
from agent.philosophy import (  # noqa: E402
    _OFFLINE_STUB,
    FEWSHOT,
    SYSTEM,
    _normalize_philosophy,
    _normalize_string_list,
    _normalize_text,
    _render,
    infer_philosophy,
)

DOCUMENTED_KEYS = {"summary", "values", "merge_bar", "direction", "evidence"}
RENDER_WHITELIST = ["frozen_at", "recent_commits", "open_issues", "open_prs",
                    "labels", "milestones", "releases", "readme_excerpt"]
RENDER_BUDGET = 12000


class RecordingLLM:
    """Records what `infer_philosophy` asks for, and answers with a fixed payload."""

    offline = False

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def chat_json(self, system, user, stub=None):
        self.calls.append({"system": system, "user": user, "stub": stub})
        return self.payload


class ExplodingLLM:
    """Fails the test if the inference path ever reaches the model."""

    offline = False

    def chat_json(self, system, user, stub=None):   # pragma: no cover - must never run
        raise AssertionError("infer_philosophy must not call the LLM for a non-dict context")


# --- Constants -----------------------------------------------------------------------------------

def test_offline_stub_is_pinned():
    assert _OFFLINE_STUB == {
        "summary": "offline stub philosophy",
        "values": [],
        "merge_bar": "unknown (offline)",
        "direction": "unknown (offline)",
        "evidence": [],
    }
    assert set(_OFFLINE_STUB) == DOCUMENTED_KEYS


def test_system_prompt_states_the_task_and_json_only_contract():
    assert "infer the maintainers' implicit philosophy" in SYSTEM
    assert "values, risk tolerance, and where the project is heading" in SYSTEM
    assert "evidence-based" in SYSTEM
    assert "Respond ONLY with JSON." in SYSTEM


def test_fewshot_carries_two_contrasting_valid_examples():
    outputs = [block.split("\n", 1)[0] for block in FEWSHOT.split("OUTPUT:\n")[1:]]
    assert len(outputs) == 2
    parsed = [json.loads(text) for text in outputs]
    for example in parsed:
        assert set(example) == DOCUMENTED_KEYS
    # Contrasting on purpose: the examples must not anchor the model to one verdict.
    assert parsed[0]["values"] == ["conservative", "stability-over-features"]
    assert parsed[1]["values"] == ["feature-first"]


# --- Text-field normalization --------------------------------------------------------------------

def test_normalize_text_returns_default_only_for_none():
    assert _normalize_text(None, "fallback") == "fallback"
    assert _normalize_text(None) == ""           # the parameter default
    # An EMPTY string is a string, so it is returned as-is -- it does NOT reach the fallback.
    assert _normalize_text("", "fallback") == ""


def test_normalize_text_returns_a_string_verbatim():
    assert _normalize_text("  padded  ", "fallback") == "  padded  "   # not stripped
    assert _normalize_text("a one-sentence summary") == "a one-sentence summary"


@pytest.mark.parametrize(("value", "expected"), [
    (5, "5"),
    (0, "0"),
    (0.5, "0.5"),
    (False, "False"),
    (True, "True"),
    (["a"], "['a']"),
    ({"k": 1}, "{'k': 1}"),
])
def test_normalize_text_coerces_every_non_string(value, expected):
    assert _normalize_text(value, "fallback") == expected


# --- List-field normalization --------------------------------------------------------------------

def test_normalize_string_list_none_is_empty():
    assert _normalize_string_list(None) == []


def test_normalize_string_list_wraps_a_bare_string():
    # A bare string is a common LLM shape for a one-element list: wrapped and stripped, not dropped.
    assert _normalize_string_list("perf-first") == ["perf-first"]
    assert _normalize_string_list("  conservative  ") == ["conservative"]


def test_normalize_string_list_drops_a_blank_string():
    assert _normalize_string_list("") == []
    assert _normalize_string_list("   ") == []
    assert _normalize_string_list("\n\t ") == []


def test_normalize_string_list_skips_none_and_blank_entries():
    assert _normalize_string_list([None, "", "  ", " a ", None, "b"]) == ["a", "b"]
    assert _normalize_string_list([]) == []
    assert _normalize_string_list([None]) == []


def test_normalize_string_list_keeps_falsy_non_none_entries():
    # Only None is skipped outright; a falsy scalar survives because its string form is not blank.
    assert _normalize_string_list([0, False, 0.0]) == ["0", "False", "0.0"]


def test_normalize_string_list_stringifies_nested_containers():
    # Nested containers are stringified, never flattened.
    assert _normalize_string_list([["n"], {"k": 1}]) == ["['n']", "{'k': 1}"]


@pytest.mark.parametrize("value", [{"a": 1}, 7, 0, False, True, 1.5, object()])
def test_normalize_string_list_rejects_a_non_list_container(value):
    assert _normalize_string_list(value) == []


# --- Philosophy mapping --------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [None, [], ["a"], "a string", 42, 0.0, True])
def test_normalize_philosophy_coerces_a_non_dict_payload_to_the_stub(payload):
    # The non-dict LLM payload: every caller still gets the documented shape, and nothing raises.
    assert _normalize_philosophy(payload, _OFFLINE_STUB) == _OFFLINE_STUB


def test_normalize_philosophy_maps_every_documented_field():
    out = _normalize_philosophy({
        "summary": 99,
        "values": "conservative",
        "merge_bar": "high bar",
        "direction": ["toward 1.0"],
        "evidence": [None, " steady patch releases ", ""],
    }, _OFFLINE_STUB)
    assert out == {
        "summary": "99",
        "values": ["conservative"],
        "merge_bar": "high bar",
        "direction": "['toward 1.0']",
        "evidence": ["steady patch releases"],
    }


def test_normalize_philosophy_falls_back_per_field():
    # A missing/None TEXT field takes the stub's value; a missing LIST field is [] -- the stub is
    # never consulted for a list.
    out = _normalize_philosophy({"summary": None}, _OFFLINE_STUB)
    assert out["summary"] == _OFFLINE_STUB["summary"]
    assert out["merge_bar"] == _OFFLINE_STUB["merge_bar"]
    assert out["direction"] == _OFFLINE_STUB["direction"]
    assert out["values"] == [] and out["evidence"] == []


def test_normalize_philosophy_drops_extra_keys():
    # The output shape cannot grow from model output.
    out = _normalize_philosophy({"summary": "s", "confidence": 0.9, "notes": ["x"]}, _OFFLINE_STUB)
    assert set(out) == DOCUMENTED_KEYS


def test_normalize_philosophy_stub_copy_is_shallow():
    # dict(stub) copies the top level only: the returned lists ARE the stub's lists, so a caller
    # that mutates them in place contaminates every later fallback. Callers treat them as read-only.
    out = _normalize_philosophy("not-a-dict", _OFFLINE_STUB)
    assert out is not _OFFLINE_STUB
    assert out["values"] is _OFFLINE_STUB["values"]
    assert out["evidence"] is _OFFLINE_STUB["evidence"]

    out["values"].append("contaminated")
    try:
        assert _normalize_philosophy("not-a-dict", _OFFLINE_STUB)["values"] == ["contaminated"]
    finally:
        _OFFLINE_STUB["values"].clear()      # leave the module-level stub as found
    assert _OFFLINE_STUB["values"] == []


# --- Inference -----------------------------------------------------------------------------------

@pytest.mark.parametrize("context", [None, "not a dict", 42, [], True, 0.0])
def test_infer_philosophy_non_dict_context_skips_the_llm_entirely(context):
    # The non-dict context fallback short-circuits before any model call.
    assert infer_philosophy(context, ExplodingLLM()) == _OFFLINE_STUB


def test_infer_philosophy_calls_chat_json_once_with_the_stub():
    llm = RecordingLLM({"summary": "s", "values": ["v"], "merge_bar": "m",
                        "direction": "d", "evidence": ["e"]})
    out = infer_philosophy({"recent_commits": []}, llm)
    assert len(llm.calls) == 1
    assert llm.calls[0]["system"] == SYSTEM
    assert llm.calls[0]["stub"] is _OFFLINE_STUB
    assert out == {"summary": "s", "values": ["v"], "merge_bar": "m",
                   "direction": "d", "evidence": ["e"]}


@pytest.mark.parametrize("payload", [None, ["a"], "a string", 7])
def test_infer_philosophy_normalizes_an_unusable_payload(payload):
    out = infer_philosophy({"recent_commits": []}, RecordingLLM(payload))
    assert out == _OFFLINE_STUB


def test_infer_philosophy_prompt_carries_the_documented_sections():
    llm = RecordingLLM({})
    infer_philosophy({"recent_commits": [{"subject": "fix: a"}]}, llm)
    user = llm.calls[0]["user"]
    assert "Infer the maintainer philosophy from this repository state." in user
    assert FEWSHOT in user
    assert "Base every field on this repository's own signals, not the examples above." in user
    assert '"summary": one-sentence characterization,' in user
    assert '"evidence": list of concrete signals you used.' in user
    # ... and the rendered context, after the examples.
    assert user.index(FEWSHOT) < user.index('"recent_commits"')


# --- Offline determinism -------------------------------------------------------------------------

def test_offline_result_is_the_normalized_stub():
    # AGENTS.md M0: VANGUARSTEW_OFFLINE=1 uses a deterministic offline stub. chat_json returns the
    # `stub` argument verbatim without a network call, so step 1 yields exactly this.
    assert infer_philosophy({"recent_commits": []}, LLM(api_key="offline")) == {
        "summary": "offline stub philosophy",
        "values": [],
        "merge_bar": "unknown (offline)",
        "direction": "unknown (offline)",
        "evidence": [],
    }


def test_offline_result_is_identical_across_calls_and_contexts():
    llm = LLM(api_key="offline")
    first = infer_philosophy({"recent_commits": [{"subject": "feat: a"}]}, llm)
    second = infer_philosophy({"recent_commits": [{"subject": "docs: totally different"}],
                               "open_issues": [{"title": "x"}]}, llm)
    assert first == second == _OFFLINE_STUB


def test_offline_result_is_a_fresh_top_level_dict():
    llm = LLM(api_key="offline")
    first = infer_philosophy({"recent_commits": []}, llm)
    second = infer_philosophy({"recent_commits": []}, llm)
    assert first is not second
    first["summary"] = "reassigned"
    assert second["summary"] == "offline stub philosophy"


# --- Rendering -----------------------------------------------------------------------------------

def test_render_keeps_the_whitelist_in_order():
    rendered = _render({
        "frozen_at": {"date": "2020-06-10T12:00:00+00:00"},
        "recent_commits": [{"subject": "fix: a", "date": "2020-06-09T12:00:00+00:00"}],
        "readme_excerpt": "a library",
        "not_whitelisted": "must not appear",
    })
    payload = json.loads(rendered)
    assert list(payload) == RENDER_WHITELIST
    assert "not_whitelisted" not in rendered
    assert payload["readme_excerpt"] == "a library"


def test_render_marks_missing_keys_null():
    payload = json.loads(_render({}))
    assert list(payload) == RENDER_WHITELIST
    assert payload["frozen_at"] is None
    assert payload["readme_excerpt"] is None


def test_render_is_truncated_at_the_prompt_budget():
    # The cap is a prompt-budget bound, not a serialization guarantee: an oversized context is cut
    # mid-value, so the rendered block is not necessarily valid JSON.
    rendered = _render({"readme_excerpt": "x" * (RENDER_BUDGET * 4), "recent_commits": []})
    assert len(rendered) == RENDER_BUDGET
    with pytest.raises(json.JSONDecodeError):
        json.loads(rendered)
