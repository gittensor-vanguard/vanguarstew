"""Contract tests for specs/004-pairwise-judge — assert the code satisfies the spec's
correctness-critical criteria: tolerant winner parsing, the dual-order position-bias defense
(agree/disagree/tie truth table), and deterministic offline anti-fluff ranking. Offline,
deterministic; the LLM is a scripted fake so no network is used.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.judge import _offline_rank, _parse_winner, judge_verbose  # noqa: E402

# Submission A carries a substantive plan; B is filler-only. A's rationale is uniquely marked
# so an "order-consistent" fake judge can prefer it regardless of presentation position.
SUB_A = {
    "philosophy": {"direction": "harden"},
    "plan": [{"title": "guard non-string score fields", "kind": "fix", "files": ["benchmark/score.py"]},
             {"title": "add regression tests", "kind": "test", "files": ["tests/test_score.py"]}],
    "rationale": "AAA_PREF_MARKER: concrete correctness work with tests.",
}
SUB_B = {
    "philosophy": {},
    "plan": ["misc", "updates", "tbd"],   # all filler → 0 substance
    "rationale": "BBB_OTHER_MARKER",
}


# --- Tolerant winner parsing (fail-safe to tie) ---------------------------------------------

def test_parse_winner_is_tolerant_and_defaults_to_tie():
    assert _parse_winner('{"winner": "A"}') == "A"
    assert _parse_winner('{"winner": "B", "why": "clearer plan"}') == "B"
    assert _parse_winner('{"winner":"tie"}') == "tie"
    assert _parse_winner('prose... "winner": "A" ...more prose') == "A"     # surrounded by prose
    assert _parse_winner('{"winner": "B') == "B"                            # truncated JSON
    assert _parse_winner("winner = A") == "A"                               # loose form
    assert _parse_winner("no verdict here") == "tie"                        # unparseable -> tie
    assert _parse_winner("") == "tie"


# --- Dual-order position-bias defense (the agree / disagree / tie truth table) ---------------

class _AlwaysFirst:
    """A purely position-biased judge: always picks whichever submission is shown FIRST."""
    offline = False

    def chat(self, system, user):
        return '{"winner": "A"}'   # "A" == the first-shown position


class _PrefersMarked:
    """A consistent judge: it prefers the SPECIFIC marked submission regardless of order,
    returning the shown-position (A=first, B=second) that the marked submission occupies."""
    offline = False

    def chat(self, system, user):
        a = user.find("AAA_PREF_MARKER")
        b = user.find("BBB_OTHER_MARKER")
        return '{"winner": "A"}' if 0 <= a < b else '{"winner": "B"}'


class _AlwaysTie:
    offline = False

    def chat(self, system, user):
        return '{"winner": "tie"}'


def test_position_biased_judge_is_forced_to_tie_via_disagree():
    winner, order = judge_verbose({}, SUB_A, SUB_B, [], _AlwaysFirst(), dual_order=True)
    assert winner == "tie"
    assert order == "disagree"   # A-first picks A, B-first picks B → disagree → tie


def test_consistent_judge_yields_agree_and_the_decisive_winner():
    winner, order = judge_verbose({}, SUB_A, SUB_B, [], _PrefersMarked(), dual_order=True)
    assert winner == "A"         # marked submission wins in BOTH orders
    assert order == "agree"


def test_both_orders_tie_reports_tie():
    winner, order = judge_verbose({}, SUB_A, SUB_B, [], _AlwaysTie(), dual_order=True)
    assert winner == "tie"
    assert order == "tie"


# --- Offline determinism + anti-fluff -------------------------------------------------------

class _Offline:
    offline = True


def test_offline_is_deterministic_and_substance_beats_filler():
    winner, order = judge_verbose({}, SUB_A, SUB_B, [], _Offline())
    assert order == "offline"
    assert winner == "A"                          # substantive plan out-ranks a filler-only plan
    # Deterministic: identical inputs → identical verdict.
    assert judge_verbose({}, SUB_A, SUB_B, [], _Offline()) == (winner, order)
    # A filler/null-padded plan scores no substance.
    assert _offline_rank(SUB_B) < _offline_rank(SUB_A)
    assert _offline_rank({"plan": ["misc", None, "updates"], "rationale": ""})[0] == 0
