"""Spec 075 contract tests for benchmark/repo_set_readiness.py (repo-set readiness gate).

Pins the as-built behavior described in specs/075-benchmark-repo-set-readiness/spec.md with
literal expected check names, ``passed`` values and detail strings. Broader coverage (the shipped
``curated.json``/``example.json`` fixtures, the CLI) lives in tests/test_repo_set_readiness.py.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set_readiness import (  # noqa: E402
    _CHECK_ROW_KEYS,
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    PRE_LLM_CUTOFF,
    _check_rows_list,
    check_readiness,
    failed_checks,
    readiness_headline,
)

LOGGER = "benchmark.repo_set_readiness"


def _named(checks):
    return {c["name"]: c for c in checks}


def _names(result):
    return [c["name"] for c in result["checks"]]


def _entry(name, before="2020-01-01", **overrides):
    entry = {"name": name, "source": f"https://github.com/org/{name}", "tier": "obscure",
             "freeze_window": {"before": before}}
    entry.update(overrides)
    return entry


def _config(*repos, **top_level):
    config = {"name": "m", "repos": list(repos)}
    config.update(top_level)
    return config


def _ready_config():
    return _config(
        _entry("tuned-a"), _entry("tuned-b"),
        _entry("held-c", held_out=True),
    )


# --- Constants -------------------------------------------------------------------------------

def test_constants_are_pinned():
    assert (DEFAULT_MIN_TUNED, DEFAULT_MIN_HELD_OUT, PRE_LLM_CUTOFF) == (2, 1, "2021-01-01")
    assert _CHECK_ROW_KEYS == ("name", "passed")


# --- Config validation -------------------------------------------------------------------------

def test_non_dict_config_reports_literal_type_name():
    cases = [
        (None, "NoneType"),
        ([1, 2], "list"),
        ("not a dict", "str"),
        (42, "int"),
        (3.14, "float"),
        (True, "bool"),
    ]
    for bad, type_name in cases:
        result = check_readiness(bad)
        assert result["passed"] is False, bad
        assert _names(result) == ["valid_config"], bad
        assert result["checks"][0]["detail"] == f"config must be a JSON object, got {type_name}", bad


def test_dict_config_failing_validate_repo_set_short_circuits():
    result = check_readiness({"repos": []})
    assert result["passed"] is False
    assert _names(result) == ["valid_config"]
    assert "must be a non-empty list" in result["checks"][0]["detail"]


def test_valid_config_passes_and_runs_remaining_checks_in_order():
    result = check_readiness(_ready_config())
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "min_tuned", "min_held_out", "pre_llm_windows", "no_placeholder_sources",
    ]
    assert result["checks"][0]["detail"] == "valid repo set (3 repo(s))"


# --- min_tuned / min_held_out -------------------------------------------------------------------

def test_min_tuned_detail_and_pass_fail():
    result = check_readiness(_ready_config(), min_tuned=2)
    checks = _named(result["checks"])
    assert checks["min_tuned"]["passed"] is True
    assert checks["min_tuned"]["detail"] == "2 tuned repo(s) >= min_tuned 2"

    result = check_readiness(_ready_config(), min_tuned=3)
    checks = _named(result["checks"])
    assert checks["min_tuned"]["passed"] is False
    assert checks["min_tuned"]["detail"] == "2 tuned repo(s) >= min_tuned 3"


def test_min_held_out_detail_and_pass_fail():
    result = check_readiness(_ready_config(), min_held_out=1)
    checks = _named(result["checks"])
    assert checks["min_held_out"]["passed"] is True
    assert checks["min_held_out"]["detail"] == "1 held-out repo(s) >= min_held_out 1"

    result = check_readiness(_ready_config(), min_held_out=2)
    checks = _named(result["checks"])
    assert checks["min_held_out"]["passed"] is False
    assert checks["min_held_out"]["detail"] == "1 held-out repo(s) >= min_held_out 2"


def test_zero_or_negative_threshold_always_passes():
    for threshold in (0, -1, -100):
        result = check_readiness(_ready_config(), min_tuned=threshold, min_held_out=threshold)
        assert failed_checks(result) == [], threshold


def test_thresholds_are_configurable_and_echoed():
    result = check_readiness(_ready_config(), min_tuned=5, min_held_out=3)
    assert result["min_tuned"] == 5
    assert result["min_held_out"] == 3
    assert result["passed"] is False


# --- pre_llm_windows -----------------------------------------------------------------------------

def test_missing_freeze_window_key_is_late():
    repo = {"name": "no-window", "source": "https://github.com/org/no-window", "tier": "obscure"}
    result = check_readiness(_config(repo, _entry("tuned-b"), _entry("held-c", held_out=True)))
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is False
    assert "no-window" in checks["pre_llm_windows"]["detail"]


def test_empty_freeze_window_is_late():
    repo = {"name": "empty-window", "source": "https://github.com/org/empty-window",
            "tier": "obscure", "freeze_window": {}}
    result = check_readiness(_config(repo, _entry("tuned-b"), _entry("held-c", held_out=True)))
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is False
    assert "empty-window" in checks["pre_llm_windows"]["detail"]


def test_freeze_window_without_before_is_late():
    repo = {"name": "no-before", "source": "https://github.com/org/no-before", "tier": "obscure",
            "freeze_window": {"min_history": 10}}
    result = check_readiness(_config(repo, _entry("tuned-b"), _entry("held-c", held_out=True)))
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is False
    assert "no-before" in checks["pre_llm_windows"]["detail"]


def test_before_after_cutoff_is_late():
    config = _config(
        _entry("tuned-a", before="2021-01-02"), _entry("tuned-b"),
        _entry("held-c", held_out=True),
    )
    result = check_readiness(config)
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is False
    assert "tuned-a" in checks["pre_llm_windows"]["detail"]


def test_before_equal_to_cutoff_is_not_late():
    config = _config(
        _entry("tuned-a", before=PRE_LLM_CUTOFF), _entry("tuned-b"),
        _entry("held-c", held_out=True),
    )
    result = check_readiness(config)
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is True
    assert checks["pre_llm_windows"]["detail"] == f"all freeze windows bounded before {PRE_LLM_CUTOFF}"


def test_late_names_sorted_in_detail():
    config = _config(
        _entry("z-late", before="2022-01-01"), _entry("a-late", before="2023-01-01"),
        _entry("held-c", held_out=True),
    )
    result = check_readiness(config)
    checks = _named(result["checks"])
    assert checks["pre_llm_windows"]["passed"] is False
    assert "['a-late', 'z-late']" in checks["pre_llm_windows"]["detail"]


# --- no_placeholder_sources ------------------------------------------------------------------

def test_placeholder_source_fails_in_entry_order():
    config = _config(
        _entry("tuned-a", source="https://github.com/OWNER/second"),
        _entry("tuned-b", source="https://github.com/OWNER/first"),
        _entry("held-c", held_out=True),
    )
    result = check_readiness(config)
    checks = _named(result["checks"])
    assert checks["no_placeholder_sources"]["passed"] is False
    assert checks["no_placeholder_sources"]["detail"] == "placeholder source(s): tuned-a, tuned-b"


# --- Result shape -----------------------------------------------------------------------------

def test_short_circuit_result_omits_repo_counts():
    result = check_readiness({"repos": []})
    assert set(result) == {"passed", "checks", "min_tuned", "min_held_out"}


def test_success_result_carries_repo_counts():
    result = check_readiness(_ready_config())
    assert result["repos_total"] == 3
    assert result["repos_tuned"] == 2
    assert result["repos_held_out"] == 1


# --- failed_checks ----------------------------------------------------------------------------

def test_failed_checks_non_dict_result():
    assert failed_checks(None) == ["result"]
    assert failed_checks([1, 2]) == ["result"]


def test_failed_checks_order_follows_checks():
    config = _config(
        _entry("tuned-a", source="https://github.com/OWNER/placeholder", before="2099-01-01"),
    )
    result = check_readiness(config)
    assert failed_checks(result) == ["min_tuned", "min_held_out", "pre_llm_windows",
                                     "no_placeholder_sources"]


# --- readiness_headline -----------------------------------------------------------------------

def test_headline_invalid_result():
    assert readiness_headline(None) == "readiness: invalid result"
    assert readiness_headline("not a result") == "readiness: invalid result"


def test_headline_no_checks_evaluated():
    assert readiness_headline({"passed": True, "checks": []}) == "readiness: no checks evaluated"
    assert readiness_headline({"passed": True}) == "readiness: no checks evaluated"
    assert readiness_headline({"passed": True, "checks": "nope"}) == "readiness: no checks evaluated"


def test_headline_ready_uses_question_mark_fallback():
    hand_built = {"passed": True, "checks": [{"name": "min_tuned", "passed": True}]}
    assert readiness_headline(hand_built) == "readiness: READY (? tuned, ? held-out)"

    full = check_readiness(_ready_config())
    assert readiness_headline(full) == "readiness: READY (2 tuned, 1 held-out)"


def test_headline_not_ready_lists_every_failed_check():
    config = _config(
        _entry("tuned-a", source="https://github.com/OWNER/placeholder", before="2099-01-01"),
    )
    result = check_readiness(config)
    line = readiness_headline(result)
    assert line == (
        "readiness: NOT READY (4/5 checks failed: min_tuned, min_held_out, "
        "pre_llm_windows, no_placeholder_sources)"
    )


# --- Checks-row sanitation --------------------------------------------------------------------

def test_check_rows_list_none_is_silent_non_list_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _check_rows_list(None) == []
    assert not caplog.records

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _check_rows_list("not a list") == []
    assert any("checks is str" in r.message for r in caplog.records)


def test_check_rows_list_skips_malformed_rows(caplog):
    good = {"name": "min_tuned", "passed": False}
    rows = [good, 42, {"passed": True}, {"name": "", "passed": True}, {"name": "x", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _check_rows_list(rows) == [good]
    assert len(caplog.records) == 4


def test_check_rows_list_warns_when_all_unusable(caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert _check_rows_list([42, "junk"]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Pure evaluation --------------------------------------------------------------------------

def test_check_readiness_does_not_mutate_config():
    config = _ready_config()
    snapshot = copy.deepcopy(config)
    check_readiness(config, min_tuned=99, min_held_out=99)
    assert config == snapshot
