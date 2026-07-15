"""Tests for the composite-score integrity gate (deterministic, offline)."""

import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.score_integrity import (  # noqa: E402
    DEFAULT_W_JUDGE,
    DEFAULT_W_OBJECTIVE,
    _check_rows_list,
    _expected_composite,
    _per_repo_weight_rows,
    _weights,
    check_score_integrity,
    failed_checks,
    integrity_headline,
)


def _artifact(composite=0.62, judge=0.7, objective=0.5, w_judge=0.6, w_objective=0.4, scored_repos=1):
    return {
        "scored_repos": scored_repos,
        "composite_mean": composite,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
        "weights": {"judge": w_judge, "objective": w_objective},
        "rows": [],
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_artifact_passes():
    art = _artifact()
    result = check_score_integrity(art)
    assert result["passed"] is True
    assert _names(result) == [
        "composite_numeric", "composite_in_range", "components_present",
        "components_in_range", "blend_consistent",
    ]


def test_blend_uses_custom_weights():
    art = _artifact(composite=0.5, judge=0.5, objective=0.5, w_judge=0.8, w_objective=0.2)
    assert check_score_integrity(art)["passed"] is True


def test_absent_weights_default_to_sixty_forty():
    art = _artifact()
    del art["weights"]
    expected = _expected_composite(0.7, 0.5, DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    art["composite_mean"] = expected
    assert check_score_integrity(art)["passed"] is True


def test_zero_weights_do_not_divide_by_zero():
    art = _artifact(composite=0.0, judge=0.5, objective=0.5, w_judge=0.0, w_objective=0.0)
    assert check_score_integrity(art)["passed"] is True


def test_mismatched_composite_fails_blend_consistent():
    art = _artifact(composite=0.99)
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert failed_checks(result) == ["blend_consistent"]


def test_out_of_range_composite_fails():
    result = check_score_integrity(_artifact(composite=1.5))
    assert result["passed"] is False
    assert "composite_in_range" in failed_checks(result)


def test_out_of_range_component_fails():
    art = _artifact(objective=1.2, composite=0.7)
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_in_range" in failed_checks(result)


def test_missing_composite_parts_fails_components_present():
    art = _artifact()
    del art["composite_parts"]
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_present" in failed_checks(result)


def test_non_dict_composite_parts_fails_components_present():
    art = _artifact()
    art["composite_parts"] = "oops"
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "components_present" in failed_checks(result)


def test_non_numeric_composite_fails_gracefully():
    art = _artifact()
    art["composite_mean"] = "high"
    result = check_score_integrity(art)
    assert result["passed"] is False
    assert "composite_numeric" in failed_checks(result)


def _gen_slice(scored_repos=1, composite=0.62, judge=0.7, objective=0.5):
    return {"scored_repos": scored_repos, "composite_mean": composite,
            "composite_parts": {"judge_mean": judge, "objective_mean": objective},
            "weights": {"judge": 0.6, "objective": 0.4}}


def test_non_finite_scored_repos_does_not_crash_the_gate():
    # Previously ValueError/OverflowError from int(scored) in _partition_scored (generalization
    # slicing). A NaN/Infinity scored_repos survives a JSON round trip but is not a usable count --
    # fall back to composite detection and still return a verdict, don't crash the gate.
    for bad in (float("nan"), float("inf"), float("-inf")):
        art = {"tuned": _gen_slice(scored_repos=bad), "held_out": _gen_slice(),
               "generalization_gap": 0.0}
        result = check_score_integrity(art)          # must not raise
        assert isinstance(result["passed"], bool), bad


def test_non_finite_composite_fails_composite_numeric():
    # A non-finite composite is not a usable number: it fails composite_numeric instead of being
    # read as real (Infinity would otherwise slip past an isinstance-only check).
    for bad in (float("nan"), float("inf"), float("-inf")):
        result = check_score_integrity(_artifact(composite=bad))
        assert result["passed"] is False
        assert "composite_numeric" in failed_checks(result), bad


def test_non_finite_component_means_fail_components_present():
    # Non-finite component means are withheld (None) rather than trusted, failing components_present.
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert "components_present" in failed_checks(check_score_integrity(_artifact(judge=bad))), bad
        assert "components_present" in failed_checks(check_score_integrity(_artifact(objective=bad))), bad


def test_non_finite_weights_fall_back_to_default_blend():
    # Non-finite weights are ignored (like any malformed weights) and the default 0.6/0.4 blend is
    # used, rather than producing a non-finite expected composite that fails the blend check.
    for bad in (float("nan"), float("inf"), float("-inf")):
        assert check_score_integrity(_artifact(w_judge=bad))["passed"] is True, bad


def test_non_finite_numeric_fields_never_raise_for_any_variant():
    # NaN, +/-Infinity, and an int too large for a float all survive a JSON round trip; none may
    # raise, for a flat run slice or a generalization partition's scored_repos.
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        for field in ("composite", "judge", "objective", "w_judge", "w_objective"):
            assert isinstance(check_score_integrity(_artifact(**{field: bad}))["passed"], bool), (field, bad)
        gen = {"tuned": _gen_slice(scored_repos=bad), "held_out": _gen_slice(),
               "generalization_gap": 0.0}
        assert isinstance(check_score_integrity(gen)["passed"], bool), ("scored_repos", bad)


def test_oversized_and_non_finite_composite_actually_fail_the_numeric_check():
    # Not merely "does not raise": an int too large for a float and a non-finite composite are not
    # usable numbers and must FAIL composite_numeric.
    for bad in (10**400, float("nan"), float("inf"), float("-inf")):
        result = check_score_integrity(_artifact(composite=bad))
        assert result["passed"] is False
        assert "composite_numeric" in failed_checks(result), bad


def test_non_finite_generalization_gap_is_handled_gracefully():
    # generalization_gap is used only to *detect* a generalization artifact (key presence); its
    # value is never converted, so a non-finite gap must not crash, and the partitions are still
    # sliced and verified.
    for bad in (float("nan"), float("inf"), float("-inf")):
        art = {"tuned": _gen_slice(), "held_out": _gen_slice(), "generalization_gap": bad}
        result = check_score_integrity(art)          # must not raise
        assert isinstance(result["passed"], bool), bad
        assert any(c["name"].startswith("tuned:") for c in result["checks"]), bad


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_score_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_score_integrity({})
    assert result["passed"] is False
    assert "composite_numeric" in failed_checks(result)


def test_tolerance_is_configurable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_score_integrity(art, tolerance=0.002)["passed"] is True
    assert check_score_integrity(art, tolerance=0.0005)["passed"] is False


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.05,
        "tuned": _artifact(composite=0.62, judge=0.7, objective=0.5),
        "held_out": _artifact(composite=0.56, judge=0.6, objective=0.5),
    }
    result = check_score_integrity(report)
    assert result["passed"] is True
    assert "tuned:blend_consistent" in _names(result)
    assert "held_out:blend_consistent" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0, "composite_mean": 0.0},
        "held_out": {"scored_repos": 0, "composite_mean": 0.0},
    }
    result = check_score_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_composite_without_scored_repos_is_checked():
    report = {
        "generalization_gap": 0.0,
        "tuned": {
            "composite_mean": 0.99,
            "composite_parts": {"judge_mean": 0.5, "objective_mean": 0.5},
            "weights": {"judge": 0.6, "objective": 0.4},
        },
        "held_out": _artifact(composite=0.6, judge=0.6, objective=0.6),
    }
    result = check_score_integrity(report)
    assert result["passed"] is False
    assert "tuned:blend_consistent" in failed_checks(result)


def test_multi_repo_weights_from_per_repo():
    art = {
        "composite_mean": 0.62,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        "per_repo": [
            {"name": "a", "composite_mean": 0.62,
             "weights": {"judge": 0.6, "objective": 0.4},
             "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5}},
        ],
    }
    assert check_score_integrity(art)["passed"] is True


# --- #635: malformed per_repo must not abort score integrity (resubmit #637) ---------

_MALFORMED_PER_REPO = [42, 3.14, True, {"name": "a"}, "not a list", b"per_repo"]


def test_per_repo_weight_rows_accepts_only_real_lists():
    rows = [{"weights": {"judge": 0.6, "objective": 0.4}}]
    for bad in _MALFORMED_PER_REPO:
        assert _per_repo_weight_rows(bad) == [], bad
    assert _per_repo_weight_rows(rows) == rows
    assert _per_repo_weight_rows(None) == []
    assert _per_repo_weight_rows([]) == []


def test_per_repo_weight_rows_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _per_repo_weight_rows(None) == []
    assert not caplog.records


def test_per_repo_weight_rows_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _per_repo_weight_rows([]) == []
    assert not caplog.records


def test_per_repo_weight_rows_warns_for_skipped_rows(caplog):
    mixed = [42, {"weights": {"judge": 0.6, "objective": 0.4}}]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert len(_per_repo_weight_rows(mixed)) == 1
    assert any("per_repo[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_per_repo_weight_rows_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _per_repo_weight_rows(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("per_repo[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_weights_uses_top_level_when_per_repo_is_non_list(caplog):
    slice_ = {
        "weights": {"judge": 0.8, "objective": 0.2},
        "per_repo": 42,
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _weights(slice_) == (0.8, 0.2)
    assert not caplog.records


def test_weights_warns_for_non_list_per_repo_without_top_level_weights(caplog):
    for bad in _MALFORMED_PER_REPO:
        slice_ = {
            "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
            "per_repo": bad,
        }
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
            assert _weights(slice_) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE), bad
        messages = [r.message for r in caplog.records]
        assert any("not a list" in m for m in messages), bad
        assert any("default blend weights" in m for m in messages), bad


def test_weights_warns_when_all_junk_per_repo_and_no_top_level_weights(caplog):
    slice_ = {
        "composite_mean": 0.62,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        "per_repo": [42, {"name": "a"}, "bad"],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _weights(slice_) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    messages = [r.message for r in caplog.records]
    assert any("per_repo[0] is int" in m for m in messages)
    assert any("no usable nested weights" in m for m in messages)
    assert any("default blend weights" in m for m in messages)

    caplog.clear()
    slice_all_junk = {**slice_, "per_repo": [42, "bad", None]}
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _weights(slice_all_junk) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    messages = [r.message for r in caplog.records]
    assert any("no usable rows" in m for m in messages)
    assert any("default blend weights" in m for m in messages)


def test_weights_warns_for_empty_per_repo_without_top_level_weights(caplog):
    slice_ = {
        "composite_mean": 0.62,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        "per_repo": [],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _weights(slice_) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    assert any("per_repo is empty" in r.message for r in caplog.records)


def test_weights_warns_for_malformed_top_level_weights(caplog):
    slice_ = {"weights": {"judge": "high", "objective": 0.4}}
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _weights(slice_) == (DEFAULT_W_JUDGE, DEFAULT_W_OBJECTIVE)
    assert any("top-level weights are missing or malformed" in r.message for r in caplog.records)


def test_check_score_integrity_survives_non_list_per_repo(caplog):
    art = {
        "composite_mean": 0.62,
        "composite_parts": {"judge_mean": 0.7, "objective_mean": 0.5},
        "per_repo": 42,
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert check_score_integrity(art)["passed"] is True
    assert any("per_repo is int" in r.message for r in caplog.records)
    assert any("default blend weights" in r.message for r in caplog.records)


# --- #781: checks row sanitization for score integrity headlines ---------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "blend_consistent"}, "not a list",
    ({"name": "blend_consistent", "passed": False},),
    range(2),
]
_FALSY_SCALAR_CHECKS = [0, 0.0, False, ""]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "blend_consistent", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_check_rows_list_treats_falsy_scalars_as_non_list(bad, caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list(bad) == []
    assert any("not a list" in r.message for r in caplog.records)


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "blend_consistent", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "blend_consistent", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_warns_when_only_malformed_dict_rows(caplog):
    junk = [{}, {"name": 42, "passed": True}, {"name": "blend_consistent", "passed": "no"}]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("missing required key(s)" in m for m in messages)
    assert any("name is int" in m for m in messages)
    assert any("passed is str" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_returns_only_valid_rows():
    valid = [
        {"name": "blend_consistent", "passed": False},
        {"name": "composite_in_range", "passed": True},
    ]
    assert _check_rows_list(valid) == valid
    mixed = [
        valid[0],
        42,
        {},
        {"name": 99, "passed": False},
        {"name": "blend_consistent", "passed": 1},
        valid[1],
    ]
    assert _check_rows_list(mixed) == valid


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert _check_rows_list([{"name": "blend_consistent"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_integrity_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert integrity_headline({"checks": bad, "passed": False}) == (
            "score integrity: no checks evaluated"
        ), bad


@pytest.mark.parametrize("bad", _FALSY_SCALAR_CHECKS)
def test_integrity_headline_survives_falsy_scalar_checks(bad):
    assert integrity_headline({"checks": bad, "passed": False}) == (
        "score integrity: no checks evaluated"
    )


def test_integrity_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "blend_consistent"}],
        [{}],
        [{"name": 42, "passed": True}],
        [{"name": "blend_consistent", "passed": 1}],
    ):
        assert integrity_headline({"checks": checks, "passed": False}) == (
            "score integrity: no checks evaluated"
        )


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "blend_consistent", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "score integrity: INCONSISTENT (1/1 checks failed: blend_consistent)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "blend_consistent"}],
        [{}],
        [42],
        [{"name": 42, "passed": True}],
        [{"name": "blend_consistent", "passed": "no"}],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "blend_consistent", "passed": False},
        42,
        {"name": "composite_in_range", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.score_integrity"):
        assert failed_checks({"checks": checks}) == ["blend_consistent"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_score_integrity(_artifact()))
    assert "INCONSISTENT" in integrity_headline(check_score_integrity(_artifact(composite=0.1)))


def test_check_score_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_score_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(_artifact(composite=0.1)), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_artifact()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr


def test_cli_missing_artifact_reports_clean_error(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(missing)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "artifact not found" in proc.stderr
    assert str(missing) in proc.stderr


def test_cli_directory_path_reports_clean_error(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.score_integrity", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "directory" in proc.stderr or "not readable" in proc.stderr


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import score_integrity as cli

    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import score_integrity as cli

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import score_integrity as cli

    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err
