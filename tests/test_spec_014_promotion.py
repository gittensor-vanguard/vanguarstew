"""Contract tests for specs/014-benchmark-promotion — assert promotion.py satisfies the spec's
EARS criteria: input coercion, numeric semantics, the tuned-partition rule for generalization
artifacts, the unscored-placeholder guard, decisive-margin resolution, fail-closed gate
evaluation, checks-row sanitization, headline branches, and pure evaluation. Offline,
deterministic.
"""

import copy
import logging
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.promotion import (  # noqa: E402
    DEFAULT_MAX_DISAGREEMENT,
    DEFAULT_MIN_COMPOSITE,
    DEFAULT_MIN_DECISIVE_MARGIN,
    _check_rows_list,
    _decisive_margin,
    _dict,
    _is_number,
    _promotion_source,
    _scored_composite,
    check_promotion,
    failed_checks,
    promotion_headline,
)

_LOGGER = "benchmark.promotion"
_CHECK_ORDER = ["run_completed", "composite_floor", "beats_baseline", "judge_trustworthy"]
_REQUIRED_KEYS = frozenset({
    "passed", "checks", "composite_mean", "decisive_margin", "disagreement_rate",
    "min_composite", "min_decisive_margin", "max_disagreement",
})


def _result(composite=0.7, margin=2, disagreement=0.1, scored_repos=None, error=None):
    r = {"composite_mean": composite, "judge_report": {"disagreement_rate": disagreement}}
    if margin is not None:
        r["decisive_margin"] = margin
    if scored_repos is not None:
        r["scored_repos"] = scored_repos
    if error is not None:
        r["error"] = error
    return r


def _generalization(tuned, held_out=None):
    return {
        "tuned": tuned,
        "held_out": held_out if held_out is not None else {"composite_mean": 0.5, "scored_repos": 2},
        "generalization_gap": 0.1,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def _check(result, name):
    return next(c for c in result["checks"] if c["name"] == name)


def _warnings(caplog):
    return [r for r in caplog.records if r.name == _LOGGER]


# --- Input coercion -------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (None, "not a dict", 42, [1, 2], ()))
def test_non_dict_result_coerced_to_empty_dict(bad):
    out = check_promotion(bad)
    assert out["passed"] is False
    assert out["composite_mean"] is None
    assert _names(out) == _CHECK_ORDER


def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    assert _dict(None) == {}
    assert _dict(42) == {}


# --- Numeric semantics ----------------------------------------------------------------------


def test_is_number_accepts_int_and_float():
    assert _is_number(3)
    assert _is_number(3.5)
    assert _is_number(0)
    assert _is_number(-2)


def test_is_number_rejects_bool():
    assert not _is_number(True)
    assert not _is_number(False)


@pytest.mark.parametrize("value", ("0.5", None, [1], {}, ()))
def test_is_number_rejects_non_numbers(value):
    assert not _is_number(value)


# --- Evaluated partition --------------------------------------------------------------------


def test_generalization_evaluated_on_tuned_partition():
    tuned = {
        "composite_mean": 0.7, "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.1},
    }
    art = _generalization(tuned)
    assert _promotion_source(art) is tuned
    out = check_promotion(art)
    assert out["composite_mean"] == 0.7          # from tuned, not the missing top level
    assert out["decisive_margin"] == 7           # 9 - 2 from tuned judge_report
    assert out["disagreement_rate"] == 0.1
    assert out["passed"] is True


@pytest.mark.parametrize("art", [
    {"composite_mean": 0.6, "decisive_margin": 2, "judge_report": {"disagreement_rate": 0.1}},
    {"tuned": None, "held_out": {"composite_mean": 0.5}, "composite_mean": 0.6,
     "decisive_margin": 2, "judge_report": {"disagreement_rate": 0.1}},
    {"tuned": {"composite_mean": 0.9}, "composite_mean": 0.6, "decisive_margin": 2,
     "judge_report": {"disagreement_rate": 0.1}},
])
def test_top_level_used_when_not_both_partitions(art):
    assert _promotion_source(art) is art
    assert check_promotion(art)["composite_mean"] == 0.6


def test_top_level_or_partition_error_marks_incomplete():
    strong = {
        "composite_mean": 0.7, "scored_repos": 3,
        "judge_report": {"wins": 9, "losses": 2, "disagreement_rate": 0.1},
    }
    top_err = _generalization(dict(strong))
    top_err["error"] = "aborted"
    assert "run_completed" in failed_checks(check_promotion(top_err))
    part_err = _generalization({**strong, "error": "partition failed"})
    assert "run_completed" in failed_checks(check_promotion(part_err))


# --- Scored composite -----------------------------------------------------------------------


def test_non_numeric_composite_is_none():
    assert _scored_composite({"composite_mean": "high"}) is None
    assert _scored_composite({}) is None
    assert _scored_composite({"composite_mean": True}) is None   # bool is not a number


def test_unscored_placeholder_is_none():
    assert _scored_composite({"composite_mean": 0.0, "scored_repos": 0}) is None


def test_genuine_zero_kept_when_scored():
    assert _scored_composite({"composite_mean": 0.0, "scored_repos": 2}) == 0.0


def test_single_repo_zero_kept():
    assert _scored_composite({"composite_mean": 0.0}) == 0.0     # no scored_repos key


def test_bool_scored_repos_not_placeholder():
    assert _scored_composite({"composite_mean": 0.7, "scored_repos": False}) == 0.7


# --- Decisive margin ------------------------------------------------------------------------


def test_margin_prefers_explicit_field():
    assert _decisive_margin({"decisive_margin": 4, "tally": {"challenger": 1, "baseline": 9}}) == 4


def test_margin_from_tally():
    assert _decisive_margin({"tally": {"challenger": 5, "baseline": 2, "tie": 1}}) == 3


def test_margin_from_judge_report():
    assert _decisive_margin({"judge_report": {"wins": 9, "losses": 2}}) == 7


def test_margin_none_when_no_source():
    assert _decisive_margin({}) is None
    assert _decisive_margin({"decisive_margin": "lots"}) is None
    assert _decisive_margin({"tally": {"challenger": "x", "baseline": 1}}) is None


def test_margin_precedence():
    explicit = {"decisive_margin": 2, "tally": {"challenger": 5, "baseline": 0},
                "judge_report": {"wins": 8, "losses": 0}}
    assert _decisive_margin(explicit) == 2
    tally_over_report = {"tally": {"challenger": 5, "baseline": 1},
                         "judge_report": {"wins": 8, "losses": 0}}
    assert _decisive_margin(tally_over_report) == 4


# --- Gate evaluation ------------------------------------------------------------------------


def test_checks_order_and_shape():
    out = check_promotion(_result())
    assert _names(out) == _CHECK_ORDER
    for row in out["checks"]:
        assert set(row) == {"name", "passed", "detail"}
        assert isinstance(row["passed"], bool)


def test_run_completed_gate():
    assert "run_completed" not in failed_checks(check_promotion(_result()))
    assert "run_completed" in failed_checks(check_promotion(_result(error="no tasks")))
    assert "run_completed" in failed_checks(check_promotion(_result(composite=0.0, scored_repos=0)))


def test_composite_floor_gate():
    assert _check(check_promotion(_result(composite=0.5), min_composite=0.5), "composite_floor")["passed"] is True
    assert _check(check_promotion(_result(composite=0.4), min_composite=0.5), "composite_floor")["passed"] is False
    assert _check(check_promotion(_result(composite="x")), "composite_floor")["passed"] is False


def test_beats_baseline_gate():
    assert _check(check_promotion(_result(margin=1), min_decisive_margin=1), "beats_baseline")["passed"] is True
    assert _check(check_promotion(_result(margin=0), min_decisive_margin=1), "beats_baseline")["passed"] is False
    out = check_promotion({"composite_mean": 0.7, "judge_report": {"disagreement_rate": 0.1}})
    assert _check(out, "beats_baseline")["passed"] is False
    assert out["decisive_margin"] is None


def test_judge_trustworthy_single_order_passes():
    row = _check(check_promotion(_result(disagreement=None)), "judge_trustworthy")
    assert row["passed"] is True
    assert "single-order" in row["detail"]


def test_judge_trustworthy_high_disagreement_fails():
    out = check_promotion(_result(disagreement=0.8), max_disagreement=0.5)
    assert _check(out, "judge_trustworthy")["passed"] is False


def test_judge_trustworthy_non_numeric_fails():
    out = check_promotion(_result(disagreement="some"))
    assert _check(out, "judge_trustworthy")["passed"] is False


def test_result_always_includes_required_keys():
    assert _REQUIRED_KEYS <= set(check_promotion(_result()))


def test_bounds_are_inclusive():
    out = check_promotion(
        _result(composite=0.5, margin=1, disagreement=0.5),
        min_composite=0.5, min_decisive_margin=1, max_disagreement=0.5,
    )
    assert out["passed"] is True


def test_default_thresholds():
    assert DEFAULT_MIN_COMPOSITE == 0.5
    assert DEFAULT_MIN_DECISIVE_MARGIN == 1
    assert DEFAULT_MAX_DISAGREEMENT == 0.5
    out = check_promotion(_result())
    assert out["min_composite"] == 0.5
    assert out["min_decisive_margin"] == 1
    assert out["max_disagreement"] == 0.5


def test_thresholds_are_configurable():
    run = _result(composite=0.55, margin=1, disagreement=0.3)
    assert check_promotion(run, min_composite=0.5, min_decisive_margin=1, max_disagreement=0.5)["passed"] is True
    assert check_promotion(run, min_composite=0.6)["passed"] is False
    assert check_promotion(run, min_decisive_margin=2)["passed"] is False
    assert check_promotion(run, max_disagreement=0.2)["passed"] is False


# --- Checks-row sanitization ----------------------------------------------------------------


def test_check_rows_list_none_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not _warnings(caplog)


@pytest.mark.parametrize("bad", (42, 3.14, True, "abc", ({"name": "run_completed", "passed": True},),
                                 range(2), {"name": "x", "passed": True}))
def test_check_rows_list_non_list_warns_and_empties(bad, caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in _warnings(caplog))


def test_check_rows_list_skips_unusable_rows(caplog):
    rows = [42, {"passed": False}, {"name": "run_completed"},
            {"name": "composite_floor", "passed": True}]
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        out = _check_rows_list(rows)
    assert out == [{"name": "composite_floor", "passed": True}]
    messages = [r.message for r in _warnings(caplog)]
    assert any("checks[0] is int" in m for m in messages)
    assert any("missing required key(s)" in m for m in messages)


def test_check_rows_list_all_unusable_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([42, "bad", None]) == []
    assert any("no usable rows" in r.message for r in _warnings(caplog))


# --- Failed checks --------------------------------------------------------------------------


def test_failed_checks_names_failed_rows():
    out = check_promotion(_result(composite=0.1))
    assert "composite_floor" in failed_checks(out)
    assert "run_completed" not in failed_checks(out)


@pytest.mark.parametrize("bad", (None, 42, "x", [{"passed": False}], [{"name": "run_completed"}],
                                 [{}], [42]))
def test_failed_checks_robust_to_malformed_checks(bad):
    assert failed_checks({"checks": bad}) == []


# --- Promotion headline ---------------------------------------------------------------------


def test_headline_promote_exact_format():
    out = check_promotion(_result(composite=0.7, margin=2, disagreement=0.1))
    assert promotion_headline(out) == "promotion: PROMOTE (composite 0.7, decisive_margin 2)"


def test_headline_hold_exact_format():
    line = promotion_headline(check_promotion(_result(composite=0.1)))
    assert line.startswith("promotion: HOLD (")
    assert "composite_floor" in line


def test_headline_no_checks_evaluated():
    assert promotion_headline({}) == "promotion: no checks evaluated"
    assert promotion_headline({"checks": []}) == "promotion: no checks evaluated"


@pytest.mark.parametrize("bad", (42, "x", ({"name": "run_completed", "passed": False},), {"a": 1}))
def test_headline_non_list_checks_shows_no_checks(bad):
    assert promotion_headline({"checks": bad, "passed": False}) == "promotion: no checks evaluated"


# --- Pure evaluation ------------------------------------------------------------------------


def test_check_does_not_mutate_result():
    run = _result()
    snapshot = copy.deepcopy(run)
    check_promotion(run)
    assert run == snapshot
