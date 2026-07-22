"""Contract tests for Spec 075 — the repo-set readiness gate (as-built, no behavior change).

Each test group pins one EARS section of ``specs/075-benchmark-repo-set-readiness/spec.md``.
Expected details and headline strings are pinned as literal values so a silent wording change
is caught. Deterministic and offline; fixture configs are built inline (no file I/O).
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


def _repo(name, source=None, held_out=False, before="2021-01-01"):
    entry = {
        "name": name,
        "source": source or f"https://github.com/org/{name}",
        "tier": "obscure",
        "freeze_window": {"before": before, "min_history": 30},
    }
    if held_out:
        entry["held_out"] = True
    return entry


def _config(repos):
    return {"name": "spec-075", "description": "d", "strategy": "s", "repos": repos}


READY = _config([
    _repo("tuned-a"), _repo("tuned-b"), _repo("held-c", held_out=True),
])


def _names(result):
    return [check["name"] for check in result["checks"]]


def _check(result, name):
    return next(check for check in result["checks"] if check["name"] == name)


# --- Gate evaluation and check order -------------------------------------------------------

def test_check_order_and_constants():
    result = check_readiness(READY)
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "min_tuned", "min_held_out", "pre_llm_windows", "no_placeholder_sources",
    ]
    assert DEFAULT_MIN_TUNED == 2
    assert DEFAULT_MIN_HELD_OUT == 1
    assert PRE_LLM_CUTOFF == "2021-01-01"


def test_check_rows_have_name_passed_detail():
    for check in check_readiness(READY)["checks"]:
        assert set(check) == {"name", "passed", "detail"}
        assert isinstance(check["name"], str)
        assert isinstance(check["passed"], bool)
        assert isinstance(check["detail"], str)


# --- Validity gate (valid_config) ----------------------------------------------------------

def test_non_dict_config_single_failed_check_with_detail():
    for bad, type_name in ((None, "NoneType"), ("cfg", "str"), (42, "int"), ([1], "list")):
        result = check_readiness(bad)
        assert result["passed"] is False
        assert _names(result) == ["valid_config"]
        assert result["checks"][0]["detail"] == (
            f"config must be a JSON object, got {type_name}"
        )


def test_repo_set_error_single_failed_check():
    # An empty repos list is well-typed but invalid; the gate reports the validator's message
    # as the single valid_config check rather than raising.
    result = check_readiness({"repos": []})
    assert result["passed"] is False
    assert _names(result) == ["valid_config"]
    assert result["checks"][0]["passed"] is False
    assert result["checks"][0]["detail"]  # stringified RepoSetError, never empty


def test_valid_config_detail_and_all_checks_evaluated():
    result = check_readiness(READY)
    assert _check(result, "valid_config")["detail"] == "valid repo set (3 repo(s))"
    assert len(result["checks"]) == 5


# --- Adequacy thresholds (min_tuned, min_held_out) -----------------------------------------

def test_min_tuned_boundary_and_detail():
    result = check_readiness(READY)  # exactly DEFAULT_MIN_TUNED tuned repos
    check = _check(result, "min_tuned")
    assert check["passed"] is True
    assert check["detail"] == "2 tuned repo(s) >= min_tuned 2"

    short = check_readiness(READY, min_tuned=3)
    check = _check(short, "min_tuned")
    assert check["passed"] is False
    assert check["detail"] == "2 tuned repo(s) >= min_tuned 3"  # same string on pass and fail


def test_min_held_out_boundary_and_detail():
    result = check_readiness(READY)  # exactly DEFAULT_MIN_HELD_OUT held-out repos
    check = _check(result, "min_held_out")
    assert check["passed"] is True
    assert check["detail"] == "1 held-out repo(s) >= min_held_out 1"

    short = check_readiness(READY, min_held_out=2)
    assert _check(short, "min_held_out")["passed"] is False
    assert failed_checks(short) == ["min_held_out"]


def test_thresholds_are_keyword_configurable():
    assert check_readiness(READY, min_tuned=1, min_held_out=1)["passed"] is True
    assert check_readiness(READY, min_tuned=3)["passed"] is False
    assert check_readiness(READY, min_held_out=2)["passed"] is False


# --- Pre-LLM freeze windows (pre_llm_windows) ----------------------------------------------

def test_before_equal_to_cutoff_passes():
    # The comparison is strictly greater: a window bounded exactly at the cutoff is pre-LLM.
    result = check_readiness(READY)
    check = _check(result, "pre_llm_windows")
    assert check["passed"] is True
    assert check["detail"] == "all freeze windows bounded before 2021-01-01"


def test_late_before_fails_with_sorted_names():
    config = _config([
        _repo("zeta", before="2023-06-01"),
        _repo("alpha", before="2022-01-02"),
        _repo("held-c", held_out=True),
    ])
    result = check_readiness(config)
    check = _check(result, "pre_llm_windows")
    assert check["passed"] is False
    # Offending names are sorted, not in repo order.
    assert check["detail"] == (
        "repo(s) sampling LLM-era history (no/late `before` bound): ['alpha', 'zeta']"
    )


def test_missing_before_fails_unbounded():
    config = json.loads(json.dumps(READY))
    config["repos"][0]["freeze_window"] = {"min_history": 30}  # no `before` bound at all
    result = check_readiness(config)
    check = _check(result, "pre_llm_windows")
    assert check["passed"] is False
    assert "tuned-a" in check["detail"]


# --- Placeholder guard (no_placeholder_sources) --------------------------------------------

def test_placeholder_sources_fail_with_joined_names():
    config = _config([
        _repo("tuned-a", source="https://github.com/OWNER/recent-active-a"),
        _repo("tuned-b", source="https://github.com/OWNER/obscure-b"),
        _repo("held-c", held_out=True),
    ])
    result = check_readiness(config)
    check = _check(result, "no_placeholder_sources")
    assert check["passed"] is False
    assert check["detail"] == "placeholder source(s): tuned-a, tuned-b"
    assert failed_checks(result) == ["no_placeholder_sources"]


def test_no_placeholders_detail():
    check = _check(check_readiness(READY), "no_placeholder_sources")
    assert check["passed"] is True
    assert check["detail"] == "no starter placeholder sources"


# --- Result shape --------------------------------------------------------------------------

def test_result_carries_thresholds_and_counts():
    result = check_readiness(READY, min_tuned=2, min_held_out=1)
    assert result["min_tuned"] == 2
    assert result["min_held_out"] == 1
    assert result["repos_total"] == 3
    assert result["repos_tuned"] == 2
    assert result["repos_held_out"] == 1
    assert result["passed"] == all(check["passed"] for check in result["checks"])


def test_invalid_result_omits_repo_counts():
    result = check_readiness({"repos": []})
    for key in ("repos_total", "repos_tuned", "repos_held_out"):
        assert key not in result
    assert result["min_tuned"] == DEFAULT_MIN_TUNED
    assert result["min_held_out"] == DEFAULT_MIN_HELD_OUT


# --- Failed checks (failed_checks) ---------------------------------------------------------

def test_failed_checks_non_dict_result():
    for bad in (None, "x", 42, [1, 2]):
        assert failed_checks(bad) == ["result"]


def test_failed_checks_names_in_order():
    config = _config([
        _repo("tuned-a", source="https://github.com/OWNER/recent-active-a", before="2023-01-01"),
    ])
    result = check_readiness(config, min_tuned=2, min_held_out=1)
    assert failed_checks(result) == [
        "min_tuned", "min_held_out", "pre_llm_windows", "no_placeholder_sources",
    ]


def test_failed_checks_row_missing_passed_counts_failed():
    assert failed_checks({"checks": [{"name": "min_tuned"}]}) == ["min_tuned"]


# --- Checks-row sanitation (_check_rows_list) ----------------------------------------------

def test_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_rows_list_non_list_warned_empty(caplog):
    row = {"name": "min_tuned", "passed": False}
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list((row,)) == []  # tuples are never coerced
        assert _check_rows_list(42) == []
    assert any("checks is tuple" in r.message for r in caplog.records)
    assert any("checks is int" in r.message for r in caplog.records)


def test_rows_list_skips_non_dict_rows_with_warning(caplog):
    rows = [42, {"name": "min_tuned", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list(rows) == [{"name": "min_tuned", "passed": True}]
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_rows_list_all_unusable_extra_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list([42]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Readiness headline --------------------------------------------------------------------

def test_headline_invalid_result_literal():
    for bad in (None, "x", 42, [1, 2]):
        assert readiness_headline(bad) == "readiness: invalid result"


def test_headline_no_checks_literal():
    for empty in ({}, {"checks": []}, {"checks": 42}, {"checks": [42]}):
        assert readiness_headline(empty) == "readiness: no checks evaluated"


def test_headline_ready_literal():
    assert readiness_headline(check_readiness(READY)) == (
        "readiness: READY (2 tuned, 1 held-out)"
    )


def test_headline_ready_question_mark_fallbacks():
    result = {"passed": True, "checks": [{"name": "valid_config", "passed": True}]}
    assert readiness_headline(result) == "readiness: READY (? tuned, ? held-out)"


def test_headline_not_ready_literal():
    result = check_readiness(READY, min_tuned=3)
    assert readiness_headline(result) == (
        "readiness: NOT READY (1/5 checks failed: min_tuned)"
    )


# --- Pure evaluation -----------------------------------------------------------------------

def test_check_readiness_no_mutation():
    config = json.loads(json.dumps(READY))
    before = json.dumps(config, sort_keys=True)
    check_readiness(config, min_tuned=3, min_held_out=2)
    assert json.dumps(config, sort_keys=True) == before
