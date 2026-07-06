"""Tests for the maintainer-philosophy step (issue #11 few-shot examples). Run:

    VANGUARSTEW_OFFLINE=1 python -m pytest -q
"""

import json
import os
import sys

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

EXPECTED_KEYS = {"summary", "values", "merge_bar", "direction", "evidence"}


def _fewshot_outputs():
    """The JSON object on the line after each 'OUTPUT:' marker (single-line examples)."""
    outs = []
    for chunk in FEWSHOT.split("OUTPUT:\n")[1:]:
        outs.append(json.loads(chunk.splitlines()[0]))
    return outs


def test_fewshot_examples_present_and_valid():
    outputs = _fewshot_outputs()
    assert len(outputs) >= 1  # acceptance: prompt includes 1-2 examples
    for ex in outputs:
        assert EXPECTED_KEYS <= set(ex), f"missing keys: {EXPECTED_KEYS - set(ex)}"
        assert isinstance(ex["values"], list) and ex["values"]
        assert isinstance(ex["evidence"], list) and ex["evidence"]
        assert isinstance(ex["summary"], str) and ex["summary"]


def test_infer_philosophy_offline_has_expected_keys():
    llm = LLM(api_key="offline")
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, llm)
    assert EXPECTED_KEYS <= set(out)


class _ListLLM:
    """A model that answers with a top-level JSON array instead of an object."""

    def chat_json(self, system, user, stub=None):
        return ["conservative", "stability-over-features"]


def test_infer_philosophy_coerces_non_dict_response_to_stub():
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _ListLLM())
    assert isinstance(out, dict)
    assert EXPECTED_KEYS <= set(out)


def test_normalize_text_coerces_scalars():
    assert _normalize_text(None, "fallback") == "fallback"
    assert _normalize_text("ship fixes", "fallback") == "ship fixes"
    assert _normalize_text(42, "fallback") == "42"


def test_normalize_string_list_coerces_to_string_list():
    assert _normalize_string_list(None) == []
    assert _normalize_string_list("conservative") == ["conservative"]
    assert _normalize_string_list(["a", "", None, 7]) == ["a", "7"]
    assert _normalize_string_list({"bad": True}) == []


def test_normalize_philosophy_maps_malformed_fields():
    stub = {
        "summary": "offline stub philosophy",
        "values": [],
        "merge_bar": "unknown (offline)",
        "direction": "unknown (offline)",
        "evidence": [],
    }
    out = _normalize_philosophy({
        "summary": None,
        "values": "feature-first",
        "merge_bar": 123,
        "direction": None,
        "evidence": None,
    }, stub)
    assert out["summary"] == "offline stub philosophy"
    assert out["values"] == ["feature-first"]
    assert out["merge_bar"] == "123"
    assert out["direction"] == "unknown (offline)"
    assert out["evidence"] == []


class _MalformedPhilosophyLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "summary": None,
            "values": "conservative",
            "merge_bar": "high bar",
            "direction": 99,
            "evidence": "recent refactors",
        }


def test_infer_philosophy_normalizes_malformed_field_types():
    out = infer_philosophy({"recent_commits": [{"subject": "init"}]}, _MalformedPhilosophyLLM())
    assert isinstance(out["summary"], str)
    assert isinstance(out["values"], list)
    assert isinstance(out["evidence"], list)
    assert out["values"] == ["conservative"]
    assert out["direction"] == "99"
    assert out["evidence"] == ["recent refactors"]

def test_infer_philosophy_handles_non_dict_context():
    from agent.llm import LLM
    llm = LLM(api_key='offline')
    assert infer_philosophy(None, llm)["summary"]
    assert infer_philosophy("not a dict", llm)["summary"]
