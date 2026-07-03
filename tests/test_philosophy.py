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
from agent.philosophy import FEWSHOT, infer_philosophy  # noqa: E402

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
