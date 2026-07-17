"""Contract tests for specs/062-benchmark-weight-integrity — assert weight_integrity.py
satisfies the spec's EARS criteria, including the deliberately strict `_is_number` (bool /
numpy / non-finite / oversized-int rejections), both `_check_slice` early returns, empty and
unscored slices, the `_is_passed` vs `_is_number` asymmetry, every headline branch, and pure
evaluation.

Expected details are pinned as LITERAL strings so a silent wording change is caught here.
numpy is not a test dependency: the numpy-scalar branches are exercised with stand-ins whose
`type(...).__name__` matches what the module keys off. Offline, deterministic.
"""

import copy
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.weight_integrity import (  # noqa: E402
    _CHECK_ROW_KEYS,
    _check_row_field,
    _check_rows_list,
    _dict,
    _expand_slice,
    _is_number,
    _is_passed,
    _partition_scored,
    _per_repo_list,
    _scored_repo,
    _weight_slices,
    check_weight_integrity,
    failed_checks,
    integrity_headline,
)

_LOGGER = "benchmark.weight_integrity"


class _NumpyFloat(float):
    """Stand-in for numpy.float64: a float subclass whose `type` is not plain `float`."""


class _NumpyBool:
    """Stand-in for numpy.bool_ — the module keys off `type(...).__name__`."""


_NumpyBool.__name__ = "bool_"


def _weights(judge=0.6, objective=0.4):
    return {"weights": {"judge": judge, "objective": objective}}


def _named(result):
    return {c["name"]: c for c in result["checks"]}


# --- Constants ---------------------------------------------------------------------------

def test_constants_are_pinned():
    assert _CHECK_ROW_KEYS == ("name", "passed")


def test_result_has_no_tolerance_key():
    # Unlike Spec 061's objective gate, this result carries only passed/checks.
    assert set(check_weight_integrity(_weights())) == {"passed", "checks"}


# --- Numeric helper (deliberately stricter than siblings) --------------------------------

def test_is_number_accepts_only_exact_finite_int_float():
    assert _is_number(0) and _is_number(3) and _is_number(0.6) and _is_number(-1)
    for bad in ("0.6", None, [1], {}, object()):
        assert _is_number(bad) is False, bad


def test_is_number_rejects_bool_and_numpy_scalars():
    # bool: type is bool, not int. numpy: type is never plain float.
    assert _is_number(True) is False and _is_number(False) is False
    assert _is_number(_NumpyFloat(0.6)) is False


def test_is_number_rejects_non_finite():
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert _is_number(bad) is False, bad


def test_is_number_rejects_oversized_int():
    # math.isfinite raises OverflowError on an int too large to convert to float.
    assert _is_number(10 ** 400) is False


# --- Dict / per_repo coercion ------------------------------------------------------------

def test_dict_helper_returns_dict_or_empty():
    assert _dict({"a": 1}) == {"a": 1}
    for bad in (42, None, "x", [1], True):
        assert _dict(bad) == {}


def test_per_repo_list_none_and_empty_are_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list(None) == []
        assert _per_repo_list([]) == []
    assert not caplog.records          # absent / zero repos are not malformed


def test_per_repo_list_warns_on_non_list_and_skips_non_dict_rows(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list(42) == []
    assert any("not a list" in r.message for r in caplog.records)

    keep = {"tasks": 1}
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _per_repo_list([keep, "junk", 7]) == [keep]
    assert any("not an object" in r.message for r in caplog.records)


# --- Scored-slice predicates -------------------------------------------------------------

def test_scored_repo_requires_positive_numeric_tasks():
    assert _scored_repo({"tasks": 3}) is True
    assert _scored_repo({"tasks": 0}) is False
    assert _scored_repo({"tasks": True}) is False        # bool rejected by _is_number
    assert _scored_repo({"tasks": "3"}) is False
    assert _scored_repo({}) is False


def test_partition_scored_prefers_per_repo_then_scored_repos_then_tasks():
    # per_repo wins: scored even though scored_repos is absent.
    assert _partition_scored({"per_repo": [{"tasks": 2}]}) is True
    assert _partition_scored({"per_repo": [{"tasks": 0}], "scored_repos": 5}) is True  # falls through
    assert _partition_scored({"scored_repos": 2}) is True
    assert _partition_scored({"scored_repos": 0}) is False
    assert _partition_scored({"tasks": 4}) is True
    assert _partition_scored({"tasks": 0}) is False
    assert _partition_scored(42) is False                 # coerced via _dict


# --- Slice selection ---------------------------------------------------------------------

def test_single_repo_slice_is_unprefixed_run():
    assert _weight_slices({}) == [("run", {})]
    names = _named(check_weight_integrity(_weights()))
    assert "weights_present" in names
    assert not any(n.startswith("run:") for n in names)


def test_multi_repo_slices_skip_unscored_rows():
    art = {"per_repo": [dict(_weights(), tasks=2), dict(_weights(), tasks=0)]}
    names = _named(check_weight_integrity(art))
    assert "repo-0:weights_present" in names
    assert not any(n.startswith("repo-1") for n in names)


def test_generalization_slices_are_partition_labelled():
    part = dict(_weights(), tasks=2)
    art = {"tuned": dict(part), "held_out": dict(part), "generalization_gap": 0.0}
    names = _named(check_weight_integrity(art))
    assert "tuned:weights_present" in names and "held_out:weights_present" in names


def test_empty_per_repo_yields_no_slices_and_artifact_shape():
    result = check_weight_integrity({"per_repo": []})
    assert _weight_slices({"per_repo": []}) == []
    assert result["passed"] is False
    assert _named(result)["artifact_shape"]["detail"] == (
        "no scored replay slice with blend weights to verify")


def test_expand_slice_returns_partition_itself_without_per_repo():
    part = {"tasks": 1}
    assert _expand_slice("tuned", part) == [("tuned", part)]


# --- Per-slice checks --------------------------------------------------------------------

def test_non_dict_weights_early_returns_single_check():
    absent = check_weight_integrity({})
    assert [c["name"] for c in absent["checks"]] == ["weights_present"]
    assert absent["checks"][0]["detail"] == (
        "weights is absent, expected an object with judge/objective")

    wrong = check_weight_integrity({"weights": 42})
    assert [c["name"] for c in wrong["checks"]] == ["weights_present"]
    assert wrong["checks"][0]["detail"] == (
        "weights is a int, expected an object with judge/objective")


def test_weights_present_reports_missing_component():
    result = check_weight_integrity({"weights": {"judge": 0.6}})
    check = _named(result)["weights_present"]
    assert check["passed"] is False
    assert check["detail"] == "judge present, objective missing"


def test_weights_non_negative_flags_negative_and_invalid():
    neg = _named(check_weight_integrity(_weights(judge=-0.1)))["weights_non_negative"]
    assert neg["passed"] is False and "judge=-0.1" in neg["detail"]

    boolean = _named(check_weight_integrity(_weights(objective=True)))["weights_non_negative"]
    assert boolean["passed"] is False and "objective=True" in boolean["detail"]

    ok = _named(check_weight_integrity(_weights()))["weights_non_negative"]
    assert ok["passed"] is True
    assert ok["detail"] == "judge and objective are finite non-negative numbers"


def test_invalid_component_early_returns_sum_check():
    result = _named(check_weight_integrity(_weights(judge="x")))
    assert result["weights_sum_positive"]["passed"] is False
    assert result["weights_sum_positive"]["detail"] == (
        "cannot sum weights: one or both components are invalid")


def test_weights_sum_positive_zero_and_positive():
    zero = _named(check_weight_integrity(_weights(judge=0, objective=0)))["weights_sum_positive"]
    assert zero["passed"] is False
    assert zero["detail"] == "judge + objective = 0.0 (not positive)"

    ok = _named(check_weight_integrity(_weights()))["weights_sum_positive"]
    assert ok["passed"] is True
    assert ok["detail"] == "judge + objective = 1.0 (positive)"


# --- Top-level result --------------------------------------------------------------------

def test_non_dict_artifact_fails_artifact_shape():
    for bad in (42, None, "x", [1]):
        result = check_weight_integrity(bad)
        assert result["passed"] is False
        assert [c["name"] for c in result["checks"]] == ["artifact_shape"]
        assert "artifact must be a JSON object" in result["checks"][0]["detail"]


def test_result_always_carries_passed_and_checks():
    for art in (42, {}, _weights()):
        result = check_weight_integrity(art)
        assert set(result) == {"passed", "checks"}
    assert check_weight_integrity(_weights())["passed"] is True


# --- Check-row sanitation ----------------------------------------------------------------

def test_is_passed_accepts_bool_rejects_int():
    assert _is_passed(True) and _is_passed(False)
    assert _is_passed(1) is False and _is_passed(0) is False
    assert _is_passed(_NumpyBool()) is True          # numpy scalar bool accepted...
    assert _is_number(_NumpyFloat(0.6)) is False     # ...while numpy scalar numbers are not


def test_check_row_field_semantics():
    assert _check_row_field("name", "ok") is True
    assert _check_row_field("name", "  ") is False
    assert _check_row_field("name", 5) is False
    assert _check_row_field("passed", True) is True
    assert _check_row_field("passed", 1) is False
    assert _check_row_field("other", "x") is False


def test_check_rows_list_none_and_empty_silent(caplog):
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(None) == []
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_skips_malformed_rows(caplog):
    good = {"name": "ok", "passed": True}
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list(42) == []
        assert _check_rows_list([
            good, "junk", {"name": "x"}, {"passed": True},
            {"name": "", "passed": True}, {"name": "n", "passed": 1},
        ]) == [good]
    assert any("not a list" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        assert _check_rows_list([{"name": "n", "passed": 1}]) == []
    assert any("no usable rows" in r.message for r in caplog.records)


# --- Failed checks and headline ----------------------------------------------------------

def test_failed_checks_names():
    result = {"checks": [{"name": "a", "passed": True}, {"name": "b", "passed": False}]}
    assert failed_checks(result) == ["b"]
    assert failed_checks(42) == []


def test_headline_no_checks():
    assert integrity_headline({"checks": []}) == "weight integrity: no checks evaluated"
    assert integrity_headline(42) == "weight integrity: no checks evaluated"
    assert integrity_headline({"checks": 42}) == "weight integrity: no checks evaluated"


def test_headline_valid():
    result = {"passed": True, "checks": [{"name": "a", "passed": True},
                                         {"name": "b", "passed": True}]}
    assert integrity_headline(result) == "weight integrity: VALID (2 checks passed)"


def test_headline_invalid_lists_failures():
    result = {"passed": False, "checks": [{"name": "a", "passed": True},
                                          {"name": "b", "passed": False}]}
    assert integrity_headline(result) == "weight integrity: INVALID (1/2 checks failed: b)"


# --- Pure evaluation ---------------------------------------------------------------------

def test_check_does_not_mutate_artifact():
    art = {"per_repo": [dict(_weights(), tasks=2)]}
    snapshot = copy.deepcopy(art)
    check_weight_integrity(art)
    assert art == snapshot
