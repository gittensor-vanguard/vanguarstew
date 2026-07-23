"""Characterization tests for Spec 079 — the repo-set acceptance-readiness gate.

These pin the observable behaviour of :mod:`benchmark.repo_set_readiness` — the gate that answers
"is a *well-formed* repo set actually *adequate* to run M3/M4 generalization acceptance on?" —
so the Spec 079 acceptance criteria have executable teeth. Every asserted value was taken from
the live module, not hand-computed.

Scope note: ``check_readiness`` delegates well-formedness to
:func:`benchmark.repo_set.validate_repo_set` (a single ``valid_config`` check) and uses
:func:`benchmark.repo_set.is_placeholder_source` for the placeholder check. Those dependency
contracts are exercised at their boundary here (the invalid-config and placeholder cases) so the
gate's reliance on them is pinned rather than left implicit.
"""

import json
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set_readiness import (  # noqa: E402
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    PRE_LLM_CUTOFF,
    _check_rows_list,
    check_readiness,
    failed_checks,
    readiness_headline,
)

# A set that passes every readiness check: 2 tuned + 2 held-out, all windows bounded before the
# pre-LLM cutoff, no placeholder sources.
VALID = {
    "name": "ready", "description": "d", "strategy": "s",
    "repos": [
        {"name": "tuned-a", "source": "https://github.com/org/a", "tier": "obscure",
         "freeze_window": {"before": "2021-01-01", "min_history": 30}},
        {"name": "tuned-b", "source": "https://github.com/org/b", "tier": "obscure",
         "freeze_window": {"before": "2021-01-01", "min_history": 30}},
        {"name": "held-c", "source": "https://github.com/org/c", "tier": "obscure",
         "held_out": True, "freeze_window": {"before": "2020-06-01", "min_history": 25}},
        {"name": "held-d", "source": "https://github.com/org/d", "tier": "obscure",
         "held_out": True, "freeze_window": {"before": "2021-01-01", "rotation_seed": 3}},
    ],
}


def _clone():
    return json.loads(json.dumps(VALID))


def _names(result):
    return [check["name"] for check in result["checks"]]


# ---- defaults / cutoff ---------------------------------------------------------------------


def test_module_defaults_and_cutoff_are_pinned():
    assert DEFAULT_MIN_TUNED == 2
    assert DEFAULT_MIN_HELD_OUT == 1
    assert PRE_LLM_CUTOFF == "2021-01-01"


# ---- the ready path ------------------------------------------------------------------------


def test_a_ready_set_passes_and_reports_all_five_checks_in_order():
    result = check_readiness(VALID)
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "min_tuned", "min_held_out", "pre_llm_windows", "no_placeholder_sources",
    ]
    assert result["repos_total"] == 4
    assert result["repos_tuned"] == 2
    assert result["repos_held_out"] == 2
    assert failed_checks(result) == []


def test_ready_headline_names_the_tuned_and_held_out_counts():
    assert readiness_headline(check_readiness(VALID)) == "readiness: READY (2 tuned, 2 held-out)"


# ---- valid_config short-circuits everything (validate_repo_set dependency) ------------------


def test_an_invalid_config_reports_only_valid_config():
    result = check_readiness({"repos": []})
    assert result["passed"] is False
    assert _names(result) == ["valid_config"]
    assert failed_checks(result) == ["valid_config"]


def test_a_non_dict_config_fails_valid_config_without_raising():
    result = check_readiness("not-a-dict")
    assert failed_checks(result) == ["valid_config"]
    assert "JSON object" in result["checks"][0]["detail"]


def test_invalid_config_headline_counts_the_single_failing_check():
    result = check_readiness({"repos": []})
    assert readiness_headline(result) == "readiness: NOT READY (1/1 checks failed: valid_config)"


# ---- the individual readiness checks -------------------------------------------------------


def test_too_few_tuned_repos_fails_only_min_tuned():
    result = check_readiness(VALID, min_tuned=3)
    assert result["passed"] is False
    assert failed_checks(result) == ["min_tuned"]


def test_too_few_held_out_repos_fails_only_min_held_out():
    config = _clone()
    config["repos"] = [repo for repo in config["repos"] if not repo.get("held_out")]
    result = check_readiness(config, min_held_out=1)
    assert failed_checks(result) == ["min_held_out"]


def test_a_late_freeze_window_fails_pre_llm_windows():
    # A window bounded after the pre-LLM cutoff samples LLM-era history — circular ground truth.
    config = _clone()
    config["repos"][0]["freeze_window"] = {"after": "2025-09-01", "recent_bias": True}
    result = check_readiness(config)
    assert "pre_llm_windows" in failed_checks(result)


def test_an_unbounded_freeze_window_fails_pre_llm_windows():
    # No `before` bound at all -> samples ALL history, including the LLM era.
    config = _clone()
    config["repos"][1]["freeze_window"] = {"min_history": 30}
    result = check_readiness(config)
    assert "pre_llm_windows" in failed_checks(result)


def test_a_starter_placeholder_source_fails_no_placeholder_sources():
    config = _clone()
    config["repos"][0]["source"] = "https://github.com/OWNER/placeholder"
    result = check_readiness(config)
    assert result["passed"] is False
    assert failed_checks(result) == ["no_placeholder_sources"]


def test_thresholds_are_configurable():
    minimal = {
        "name": "m",
        "repos": [
            {"name": "a", "source": "https://github.com/org/a", "tier": "obscure",
             "freeze_window": {"before": "2021-01-01", "min_history": 30}},
            {"name": "b", "source": "https://github.com/org/b", "tier": "obscure",
             "freeze_window": {"before": "2021-01-01", "min_history": 20}},
            {"name": "c", "source": "https://github.com/org/c", "tier": "obscure",
             "held_out": True, "freeze_window": {"before": "2021-01-01", "min_history": 25}},
        ],
    }
    assert check_readiness(minimal, min_tuned=1, min_held_out=1)["passed"] is True
    assert check_readiness(minimal, min_tuned=3, min_held_out=1)["passed"] is False


# ---- failed_checks / readiness_headline on malformed results (never raise) ------------------


def test_failed_checks_on_a_non_dict_result_returns_a_sentinel():
    assert failed_checks(None) == ["result"]
    assert failed_checks("nope") == ["result"]


def test_failed_checks_tolerates_a_non_list_checks_container():
    assert failed_checks({"checks": 42}) == []


def test_readiness_headline_on_malformed_results():
    assert readiness_headline(42) == "readiness: invalid result"
    assert readiness_headline({"checks": []}) == "readiness: no checks evaluated"
    assert readiness_headline({}) == "readiness: no checks evaluated"


# ---- _check_rows_list sanitizer edges (each isolated so a partial regression is pinpointable)


def test_check_rows_list_returns_empty_for_none_and_empty():
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_warns_and_empties_a_tuple(caplog):
    # A tuple is a non-list iterable and must never be coerced — it degrades to empty with a warn.
    with caplog.at_level(logging.WARNING):
        rows = _check_rows_list(({"name": "min_tuned", "passed": True},))
    assert rows == []
    assert any("not a list" in rec.message for rec in caplog.records)


def test_check_rows_list_skips_a_non_dict_row():
    assert _check_rows_list([{"name": "ok", "passed": True}, "not-a-row"]) == \
        [{"name": "ok", "passed": True}]


def test_check_rows_list_skips_a_row_missing_required_keys():
    assert [r["name"] for r in _check_rows_list([{"name": "ok", "passed": True}, {"name": "x"}])] \
        == ["ok"]


def test_check_rows_list_skips_a_blank_name():
    assert [r["name"] for r in _check_rows_list([{"name": "ok", "passed": True},
                                                 {"name": "  ", "passed": True}])] == ["ok"]


def test_check_rows_list_skips_a_non_bool_passed():
    # "yes" is truthy but not a bool; a check row's pass/fail must be a real bool, not coerced.
    assert [r["name"] for r in _check_rows_list([{"name": "ok", "passed": True},
                                                 {"name": "n", "passed": "yes"}])] == ["ok"]
