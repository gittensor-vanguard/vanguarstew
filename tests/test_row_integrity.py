"""Tests for the per-task row integrity gate (deterministic, offline)."""

import copy
import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.row_integrity import (  # noqa: E402
    _check_rows_list,
    _row_slices,
    check_row_integrity,
    failed_checks,
    integrity_headline,
)
from benchmark.score import composite_score  # noqa: E402
from scripts import row_integrity as cli  # noqa: E402

ROWS = [
    {
        "winner": "challenger",
        "objective": {"module_recall": 1.0},
        "composite": composite_score("A", {"module_recall": 1.0}, 0.6, 0.4),
    },
    {
        "winner": "baseline",
        "objective": {"module_recall": 0.0},
        "composite": composite_score("B", {"module_recall": 0.0}, 0.6, 0.4),
    },
    {
        "winner": "tie",
        "objective": {"module_recall": 0.5},
        "composite": composite_score("tie", {"module_recall": 0.5}, 0.6, 0.4),
    },
]


def _artifact(rows=None, w_judge=0.6, w_objective=0.4, composite_mean=None):
    rows = copy.deepcopy(ROWS if rows is None else rows)
    dict_rows = [r for r in rows if isinstance(r, dict)]
    composites = [r["composite"] for r in dict_rows]
    judge_parts = {"challenger": 1.0, "tie": 0.5, "baseline": 0.0}
    objective_parts = [r["objective"]["module_recall"] for r in dict_rows]
    mean_composite = composite_mean
    if mean_composite is None:
        mean_composite = round(sum(composites) / len(composites), 3) if composites else 0.0
    return {
        "tasks": len(dict_rows),
        "composite_mean": mean_composite,
        "composite_parts": {
            "judge_mean": round(sum(judge_parts[r["winner"]] for r in dict_rows) / len(dict_rows), 3),
            "objective_mean": round(sum(objective_parts) / len(dict_rows), 3),
        },
        "weights": {"judge": w_judge, "objective": w_objective},
        "rows": rows,
    }


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_consistent_single_repo_passes():
    result = check_row_integrity(_artifact())
    assert result["passed"] is True
    assert _names(result) == [
        "rows_present", "row_composites_consistent", "composite_mean_matches_rows",
        "judge_mean_matches_rows", "objective_mean_matches_rows",
    ]


def test_wrong_row_composite_fails():
    art = _artifact()
    art["rows"][0]["composite"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "row_composites_consistent" in failed_checks(result)


def test_composite_mean_mismatch_fails():
    art = _artifact(composite_mean=0.99)
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "composite_mean_matches_rows" in failed_checks(result)


def test_judge_mean_mismatch_fails():
    art = _artifact()
    art["composite_parts"]["judge_mean"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "judge_mean_matches_rows" in failed_checks(result)


def test_objective_mean_mismatch_fails():
    art = _artifact()
    art["composite_parts"]["objective_mean"] = 0.99
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "objective_mean_matches_rows" in failed_checks(result)


def test_custom_weights_are_respected():
    rows = [
        {
            "winner": "challenger",
            "objective": {"module_recall": 0.5},
            "composite": composite_score("A", {"module_recall": 0.5}, 0.8, 0.2),
        },
    ]
    art = _artifact(rows=rows, w_judge=0.8, w_objective=0.2)
    assert check_row_integrity(art)["passed"] is True


def test_corrupt_string_per_repo_row_fails_closed():
    # A per_repo row serialized as a raw error string (not a result dict) is silently dropped by
    # _per_repo_list, so a partial artifact with one clean scored repo used to pass as CONSISTENT.
    # It must fail closed instead -- matching run_clean (#1357), error_repo_share (#1362), and
    # tally_integrity (#1453).
    art = {"per_repo": [_artifact(), "CLONE FAILED: fatal"]}
    result = check_row_integrity(art)
    assert result["passed"] is False
    assert "per_repo_rows_wellformed" in failed_checks(result)


def test_corrupt_string_row_in_generalization_partition_fails_closed():
    held = _artifact()
    held["scored_repos"] = 1
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [_artifact(), "boom"]},
        "held_out": held,
    }
    result = check_row_integrity(report)
    assert result["passed"] is False
    assert "per_repo_rows_wellformed" in failed_checks(result)


def test_wellformed_per_repo_rows_pass_the_check():
    # Control: an int row and a whitespace-only string are ignored (not corrupt) -- only a
    # non-empty string is flagged -- so a clean multi-repo run stays CONSISTENT and reports the
    # well-formedness check as passing.
    art = {"per_repo": [_artifact(), 42, "   "]}
    result = check_row_integrity(art)
    assert result["passed"] is True
    assert "per_repo_rows_wellformed" in _names(result)
    assert "per_repo_rows_wellformed" not in failed_checks(result)


def test_tolerance_is_configurable():
    art = _artifact()
    art["composite_mean"] = art["composite_mean"] + 0.001
    assert check_row_integrity(art, tolerance=0.002)["passed"] is True
    assert check_row_integrity(art, tolerance=0.0005)["passed"] is False


def test_non_dict_artifact_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_row_integrity(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["artifact_shape"]


def test_empty_dict_fails_gracefully():
    result = check_row_integrity({})
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_multi_repo_checks_each_scored_entry():
    art = {
        "per_repo": [
            _artifact(),
            {"tasks": 0, "rows": []},
            _artifact(rows=ROWS[:1]),
        ],
    }
    result = check_row_integrity(art)
    assert result["passed"] is True
    assert "repo-0:composite_mean_matches_rows" in _names(result)
    assert "repo-2:row_composites_consistent" in _names(result)
    assert not any(name.startswith("repo-1:") for name in _names(result))


def test_generalization_checks_each_scored_partition():
    report = {
        "generalization_gap": 0.1,
        "tuned": {"scored_repos": 1, "per_repo": [_artifact()]},
        "held_out": {"scored_repos": 1, "per_repo": [_artifact(rows=ROWS[:2])]},
    }
    result = check_row_integrity(report)
    assert result["passed"] is True
    assert "tuned:repo-0:judge_mean_matches_rows" in _names(result)
    assert "held_out:repo-0:rows_present" in _names(result)


def test_generalization_skips_unscored_partitions():
    report = {
        "generalization_gap": None,
        "tuned": {"scored_repos": 0},
        "held_out": {"scored_repos": 0},
    }
    result = check_row_integrity(report)
    assert result["passed"] is False
    assert failed_checks(result) == ["artifact_shape"]


def test_generalization_per_repo_without_scored_repos_is_checked():
    import copy
    held = _artifact()
    held["scored_repos"] = 1
    bad_rows = copy.deepcopy(ROWS)
    bad_rows[0]["composite"] = 0.99
    report = {
        "generalization_gap": 0.0,
        "tuned": {"per_repo": [_artifact(rows=bad_rows)]},
        "held_out": held,
    }
    result = check_row_integrity(report)
    assert result["passed"] is False
    assert "tuned:repo-0:row_composites_consistent" in failed_checks(result)


def test_row_slices_expands_partition_rows():
    part = {"scored_repos": 1, "rows": ROWS, **_artifact(rows=ROWS)}
    slices = _row_slices({"tuned": part, "held_out": part, "generalization_gap": 0.0})
    assert ("tuned", part) in slices


def test_malformed_rows_are_skipped_with_warning(caplog):
    art = {
        "tasks": 1,
        "composite_mean": 1.0,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": 1.0},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": [{"winner": "challenger", "objective": {"module_recall": 1.0},
                  "composite": 1.0}, 42],
    }
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        result = check_row_integrity(art)
    assert result["passed"] is True
    assert any("rows[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_reports_consistent_and_inconsistent():
    assert "CONSISTENT" in integrity_headline(check_row_integrity(_artifact()))
    art = _artifact()
    art["rows"][0]["composite"] = 0.0
    assert "INCONSISTENT" in integrity_headline(check_row_integrity(art))


# --- #723: checks row sanitization for row integrity headlines (resubmit of #725) ----

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "rows_present"}, "not a list",
    ({"name": "rows_present", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "rows_present", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_empty_list_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list([]) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "rows_present", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "rows_present", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)
    assert not any("no usable rows" in r.message for r in caplog.records)


def test_check_rows_list_warns_when_every_entry_is_unusable(caplog):
    junk = [42, "bad", None]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list(junk) == []
    messages = [r.message for r in caplog.records]
    assert any("checks[0] is int" in m for m in messages)
    assert any("no usable rows" in m for m in messages)


def test_check_rows_list_skips_row_missing_name(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list([{"passed": False}]) == []
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_row_missing_passed(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list([{"name": "rows_present"}]) == []
    assert any("missing required key(s) ['passed']" in r.message for r in caplog.records)


def test_check_rows_list_skips_empty_dict(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert _check_rows_list([{}]) == []
    assert any("missing required key(s)" in r.message for r in caplog.records)


def test_integrity_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert integrity_headline({"checks": bad, "passed": False}) == (
            "row integrity: no checks evaluated"
        ), bad


def test_integrity_headline_survives_rows_missing_required_keys():
    for checks in (
        [{"passed": False}],
        [{"name": "rows_present"}],
        [{}],
    ):
        assert integrity_headline({"checks": checks, "passed": False}) == (
            "row integrity: no checks evaluated"
        )


def test_integrity_headline_uses_sanitized_row_count(caplog):
    checks = [{"name": "rows_present", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        line = integrity_headline({"checks": checks, "passed": False})
    assert line == "row integrity: INCONSISTENT (1/1 checks failed: rows_present)"
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_integrity_headline_logs_warning_for_non_list_checks(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        line = integrity_headline({"checks": 42, "passed": False})
    assert line == "row integrity: no checks evaluated"
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert failed_checks({"checks": bad}) == [], bad


def test_failed_checks_never_raises_on_malformed_rows():
    for checks in (
        [{"passed": False}],
        [{"name": "rows_present"}],
        [{}],
        [42],
    ):
        assert failed_checks({"checks": checks}) == []


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [
        {"name": "rows_present", "passed": False},
        42,
        {"name": "composite_mean_matches_rows", "passed": True},
    ]
    with caplog.at_level(logging.WARNING, logger="benchmark.row_integrity"):
        assert failed_checks({"checks": checks}) == ["rows_present"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_row_integrity_does_not_mutate_the_artifact():
    art = _artifact()
    before = json.dumps(art, sort_keys=True)
    check_row_integrity(art)
    assert json.dumps(art, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_inconsistent(tmp_path):
    bad = tmp_path / "bad.json"
    art = _artifact()
    art["rows"][0]["composite"] = 0.0
    bad.write_text(json.dumps(art), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.row_integrity", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "INCONSISTENT" in proc.stderr


def test_cli_passes_for_consistent_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_artifact()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.row_integrity", str(good), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "CONSISTENT" in proc.stderr


# --- #1613: clean errors instead of raw errno text on a bad artifact path -----------------


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.row_integrity", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_directory_path(tmp_path):
    result = _run_cli(str(tmp_path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "directory" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(path))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_load_artifact_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "artifact path is a directory, not a file" in err and "Traceback" not in err


def test_load_artifact_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_artifact_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_artifact(str(tmp_path / "run.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "cannot read artifact" in err and "Traceback" not in err


# --- non-finite (NaN/Infinity) numeric fields must fail checks, not raise (#927) ----------


def test_non_finite_tasks_fail_the_shape_check_instead_of_raising():
    # the exact repro from #927: previously ValueError from int(float("nan"))
    result = check_row_integrity(
        {"per_repo": [{"tasks": float("nan"), "rows": [],
                       "weights": {"judge": 0.6, "objective": 0.4}}]}
    )
    assert result["passed"] is False
    assert "artifact_shape" in [c["name"] for c in result["checks"] if not c["passed"]]


def test_non_finite_numeric_fields_never_raise_for_any_variant():
    for bad in (float("nan"), float("inf"), float("-inf"), 10**400):
        art = _artifact()
        art["tasks"] = bad
        result = check_row_integrity(art)          # must not raise
        assert isinstance(result["passed"], bool), bad

        art = _artifact()
        art["weights"]["judge"] = bad
        result = check_row_integrity(art)          # must not raise
        assert isinstance(result["passed"], bool), bad
