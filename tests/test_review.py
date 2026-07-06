"""Tests for the maintainer-assist review (offline, deterministic)."""

import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.environ["VANGUARSTEW_OFFLINE"] = "1"

from agent.llm import LLM  # noqa: E402
from agent.review import (  # noqa: E402
    ACTIONS,
    VALUE_LABELS,
    _normalize_bool,
    _normalize_concerns,
    _normalize_review_action,
    _normalize_value_label,
    review_pr,
)


def test_review_offline_shape():
    llm = LLM(api_key="offline")
    pr = {"number": 30, "title": "Semver-aware bump scoring", "author": "x",
          "additions": 175, "deletions": 4, "body": "Fixes #10", "diff": "",
          "files": ["benchmark/score.py", "tests/test_score.py"]}
    rev = review_pr(pr, None, llm)
    for k in ("action", "value_label", "scope_ok", "tests_present", "summary",
              "concerns", "recommendation"):
        assert k in rev
    assert rev["action"] in ACTIONS
    assert rev["tests_present"] is True   # a tests/ file is present


def test_review_detects_no_tests():
    llm = LLM(api_key="offline")
    pr = {"number": 1, "title": "tweak", "author": "y", "additions": 5, "deletions": 0,
          "files": ["benchmark/score.py"], "body": "", "diff": ""}
    assert review_pr(pr, None, llm)["tests_present"] is False


def test_review_tolerates_missing_fields():
    llm = LLM(api_key="offline")
    rev = review_pr({}, None, llm)
    assert rev["action"] in ACTIONS


def test_normalize_review_action_maps_synonyms():
    assert _normalize_review_action("approve") == "merge"
    assert _normalize_review_action("accept") == "merge"
    assert _normalize_review_action("request changes") == "request-changes"
    assert _normalize_review_action("changes requested") == "request-changes"
    assert _normalize_review_action("decline") == "reject"
    assert _normalize_review_action("close") == "reject"
    assert _normalize_review_action("abstain") == "comment"
    assert _normalize_review_action("hold") == "comment"
    assert _normalize_review_action("unknown") == "comment"


def test_normalize_review_action_tolerates_non_string_input():
    assert _normalize_review_action(["merge"]) == "comment"
    assert _normalize_review_action({"value": "merge"}) == "comment"
    assert _normalize_review_action(42) == "comment"
    assert _normalize_review_action(4.2) == "comment"
    assert _normalize_review_action(None) == "comment"
    assert _normalize_review_action(True) == "comment"
    assert _normalize_review_action(b"merge") == "comment"


def test_normalize_review_action_tolerates_empty_and_whitespace_strings():
    assert _normalize_review_action("") == "comment"
    assert _normalize_review_action("   ") == "comment"
    assert _normalize_review_action("\t\n") == "comment"


def test_normalize_review_action_logs_a_warning_for_non_string_input(caplog):
    with caplog.at_level(logging.WARNING, logger="agent.review"):
        assert _normalize_review_action(["merge"]) == "comment"
    assert any("non-string action" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="agent.review"):
        assert _normalize_review_action("approve") == "merge"
    assert not caplog.records


def test_normalize_value_label_repairs_prefix_and_case():
    assert _normalize_value_label("mult:core-correctness") == "mult:core-correctness"
    assert _normalize_value_label("core-correctness") == "mult:core-correctness"
    assert _normalize_value_label("core correctness") == "mult:core-correctness"
    assert _normalize_value_label("core_correctness") == "mult:core-correctness"
    assert _normalize_value_label("leakage integrity") == "mult:leakage-integrity"
    assert _normalize_value_label("MULT:LEAKAGE-INTEGRITY") == "mult:leakage-integrity"
    assert _normalize_value_label("maintenance") == "mult:maintenance"
    assert _normalize_value_label("bogus") == "mult:maintenance"
    assert _normalize_value_label(None) == "mult:maintenance"


def test_normalize_bool_and_concerns():
    assert _normalize_bool("yes") is True
    assert _normalize_bool("false") is False
    assert _normalize_bool(None, default=True) is True
    assert _normalize_concerns("missing tests") == ["missing tests"]
    assert _normalize_concerns(["a", None, 7]) == ["a", "7"]


class _MalformedReviewLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": "approve",
            "value_label": "core-correctness",
            "scope_ok": "yes",
            "tests_present": 0,
            "summary": None,
            "concerns": "missing edge-case coverage",
            "recommendation": None,
        }


def test_review_pr_normalizes_malformed_field_types():
    rev = review_pr({"files": []}, None, _MalformedReviewLLM())
    assert rev["action"] == "merge"
    assert rev["value_label"] in VALUE_LABELS
    assert rev["value_label"] == "mult:core-correctness"
    assert rev["scope_ok"] is True
    assert rev["tests_present"] is False
    assert rev["summary"] == ""
    assert rev["concerns"] == ["missing edge-case coverage"]
    assert rev["recommendation"] == ""


class _NonStringActionReviewLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {
            "action": ["merge", "reject"],
            "value_label": "mult:core-correctness",
            "scope_ok": True,
            "tests_present": True,
            "summary": "adds a missing guard",
            "concerns": ["needs a regression test"],
            "recommendation": "request changes until tests land",
        }


def test_review_pr_survives_non_string_action_field():
    rev = review_pr({"number": 1, "title": "t", "files": ["tests/test_x.py"]}, None,
                     _NonStringActionReviewLLM())
    # the malformed field degrades safely...
    assert rev["action"] == "comment"
    # ...and every other field is still normalized correctly, unaffected by the bad action.
    assert rev["value_label"] == "mult:core-correctness"
    assert rev["scope_ok"] is True
    assert rev["tests_present"] is True
    assert rev["summary"] == "adds a missing guard"
    assert rev["concerns"] == ["needs a regression test"]
    assert rev["recommendation"] == "request changes until tests land"


class _NearMissReviewLLM:
    offline = False

    def chat_json(self, system, user, stub=None):
        return {"action": "approve", "value_label": "maintenance"}


def test_review_pr_maps_near_miss_action_and_value_label_to_canonical_vocab():
    rev = review_pr({"files": []}, None, _NearMissReviewLLM())
    assert rev["action"] in ACTIONS
    assert rev["action"] == "merge"
    assert rev["value_label"] in VALUE_LABELS
    assert rev["value_label"] == "mult:maintenance"


# --- #414: non-list / non-string PR file paths must not abort review_pr --------------------

_MALFORMED_FILES = [42, 3.14, True, "agent/foo.py", {"path": "tests/x.py"}, None]


def test_review_pr_tolerates_non_list_files_field():
    llm = LLM(api_key="offline")
    for bad in _MALFORMED_FILES:
        rev = review_pr({"number": 1, "title": "Fix bug", "author": "alice", "files": bad},
                        None, llm)
        assert rev["action"] in ACTIONS
        assert rev["tests_present"] is False


def test_review_pr_keeps_only_string_paths_from_files_list():
    llm = LLM(api_key="offline")
    pr = {"number": 1, "title": "Fix bug", "author": "alice",
          "files": [None, 42, "", "  ", "tests/test_x.py", {"path": "ignored"}]}
    assert review_pr(pr, None, llm)["tests_present"] is True


def test_review_pr_files_list_unchanged_for_well_formed_paths():
    llm = LLM(api_key="offline")
    pr = {"number": 30, "title": "Semver-aware bump scoring", "author": "x",
          "additions": 175, "deletions": 4, "body": "Fixes #10", "diff": "",
          "files": ["benchmark/score.py", "tests/test_score.py"]}
    assert review_pr(pr, None, llm)["tests_present"] is True
