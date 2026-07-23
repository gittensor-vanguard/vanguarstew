"""Tests for the repo-set acceptance-readiness gate (deterministic, offline)."""

import json
import logging
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import (  # noqa: E402
    CURATED_REPO_SET,
    EXAMPLE_REPO_SET,
    is_placeholder_source,
)
from benchmark.repo_set_readiness import (  # noqa: E402
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    _check_rows_list,
    check_readiness,
    failed_checks,
    readiness_headline,
)

VALID = {
    "name": "ready",
    "description": "d",
    "strategy": "s",
    "repos": [
        {"name": "tuned-a", "source": "https://github.com/org/a", "tier": "obscure",
         "freeze_window": {"before": "2021-01-01", "min_history": 30, "horizon_days": 60}},
        {"name": "tuned-b", "source": "https://github.com/org/b", "tier": "obscure",
         "freeze_window": {"before": "2021-01-01", "min_history": 30}},
        {"name": "held-c", "source": "https://github.com/org/c", "tier": "obscure",
         "held_out": True, "freeze_window": {"before": "2020-06-01", "min_history": 25}},
        {"name": "held-d", "source": "https://github.com/org/d", "tier": "obscure",
         "held_out": True, "freeze_window": {"before": "2021-01-01", "rotation_seed": 3}},
    ],
}


def _names(result):
    return [check["name"] for check in result["checks"]]


def test_is_placeholder_source_matches_starter_urls_only():
    assert is_placeholder_source("https://github.com/OWNER/recent-active-a") is True
    assert is_placeholder_source("https://github.com/real-owner/OWNER-tools") is False
    assert is_placeholder_source("https://github.com/org/hatch") is False
    assert is_placeholder_source(42) is False


def test_a_ready_set_passes_all_checks():
    result = check_readiness(VALID)
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "min_tuned", "min_held_out", "pre_llm_windows", "no_placeholder_sources",
    ]


def test_shipped_curated_json_passes_readiness():
    with open(CURATED_REPO_SET, encoding="utf-8") as handle:
        config = json.load(handle)
    result = check_readiness(config)
    assert result["passed"] is True
    assert result["repos_tuned"] >= DEFAULT_MIN_TUNED
    assert result["repos_held_out"] >= DEFAULT_MIN_HELD_OUT


def test_shipped_example_json_fails_on_placeholder_sources():
    with open(EXAMPLE_REPO_SET, encoding="utf-8") as handle:
        config = json.load(handle)
    result = check_readiness(config)
    assert result["passed"] is False
    assert failed_checks(result) == ["no_placeholder_sources"]
    assert result["checks"][0]["passed"] is True


def test_too_few_tuned_repos_fails_min_tuned():
    config = {
        "name": "m",
        "repos": [
            {"name": "held-c", "source": "https://github.com/org/c", "tier": "obscure",
             "held_out": True, "freeze_window": {"before": "2021-01-01", "min_history": 25}},
            {"name": "held-d", "source": "https://github.com/org/d", "tier": "obscure",
             "held_out": True, "freeze_window": {"before": "2021-01-01", "rotation_seed": 3}},
            {"name": "tuned-a", "source": "https://github.com/org/a", "tier": "obscure",
             "freeze_window": {"before": "2021-01-01", "min_history": 30}},
        ],
    }
    result = check_readiness(config, min_tuned=2)
    assert result["passed"] is False
    assert failed_checks(result) == ["min_tuned"]


def test_too_few_held_out_repos_fails_min_held_out():
    config = {
        "name": "m",
        "repos": [repo for repo in VALID["repos"] if not repo.get("held_out")],
    }
    result = check_readiness(config, min_held_out=1)
    assert result["passed"] is False
    assert failed_checks(result) == ["min_held_out"]


def test_llm_era_window_fails_pre_llm_windows():
    # A freeze window bounded after the LLM-era cutoff (or unbounded) samples history whose
    # "next maintainer actions" may themselves be LLM-written — circular ground truth. This
    # replaced the retired `both_tiers` check (see benchmark/repo_set_readiness.py).
    config = json.loads(json.dumps(VALID))
    config["repos"][0]["freeze_window"] = {"after": "2025-09-01", "recent_bias": True}
    result = check_readiness(config)
    assert result["passed"] is False
    assert "pre_llm_windows" in failed_checks(result)


def test_unbounded_window_fails_pre_llm_windows():
    # No `before` bound at all -> samples ALL history, including the LLM era.
    config = json.loads(json.dumps(VALID))
    config["repos"][1]["freeze_window"] = {"min_history": 30}
    result = check_readiness(config)
    assert result["passed"] is False
    assert "pre_llm_windows" in failed_checks(result)


def test_starter_placeholder_fails_no_placeholder_sources():
    config = json.loads(json.dumps(VALID))
    config["repos"][0]["source"] = "https://github.com/OWNER/placeholder"
    result = check_readiness(config)
    assert result["passed"] is False
    assert "no_placeholder_sources" in failed_checks(result)


def test_invalid_config_fails_only_valid_config():
    result = check_readiness({"repos": []})
    assert result["passed"] is False
    assert failed_checks(result) == ["valid_config"]
    assert _names(result) == ["valid_config"]


def test_empty_dict_fails_valid_config():
    result = check_readiness({})
    assert result["passed"] is False
    assert failed_checks(result) == ["valid_config"]


def test_missing_repos_key_fails_valid_config():
    result = check_readiness({"name": "no-repos"})
    assert result["passed"] is False
    assert failed_checks(result) == ["valid_config"]


def test_non_dict_config_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_readiness(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["valid_config"]
        assert "JSON object" in result["checks"][0]["detail"]


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


def test_readiness_headline_reports_ready_and_not_ready():
    assert "READY" in readiness_headline(check_readiness(VALID))
    assert "NOT READY" in readiness_headline(check_readiness({"repos": []}))


def test_failed_checks_reports_malformed_result():
    assert failed_checks(None) == ["result"]
    assert failed_checks({"checks": 42}) == []


# --- #712: checks hardening for readiness headline / failed_checks --------------------

_MALFORMED_CHECKS = [
    42, 3.14, True, {"name": "min_tuned"}, "not a list",
    ({"name": "min_tuned", "passed": False},),
    range(2),
]


def test_check_rows_list_accepts_only_real_lists():
    rows = [{"name": "min_tuned", "passed": True}]
    for bad in _MALFORMED_CHECKS:
        assert _check_rows_list(bad) == [], bad
    assert _check_rows_list(rows) == rows
    assert _check_rows_list(None) == []
    assert _check_rows_list([]) == []


def test_check_rows_list_missing_key_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list(None) == []
    assert not caplog.records


def test_check_rows_list_warns_for_tuple_container(caplog):
    row = ({"name": "min_tuned", "passed": False},)
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list(row) == []
    assert any("checks is tuple" in r.message for r in caplog.records)


def test_check_rows_list_warns_for_skipped_rows(caplog):
    mixed = [42, {"name": "min_tuned", "passed": True}]
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert len(_check_rows_list(mixed)) == 1
    assert any("checks[0] is int" in r.message for r in caplog.records)


def test_check_rows_list_skips_a_dict_row_missing_or_mistyped_name_or_passed(caplog):
    # #1660: the row guard only skipped non-dict rows, so a dict row missing "name"/"passed" (or
    # carrying a wrong-typed one) slipped through and made the row["name"]/row["passed"] reads
    # raise KeyError. Such a row is now skipped with a warning, mirroring the sibling gates.
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list([{"passed": False}]) == []          # missing name
        assert _check_rows_list([{"name": "min_tuned"}]) == []      # missing passed
        assert _check_rows_list([{"name": 99, "passed": False}]) == []   # non-str name
        assert _check_rows_list([{"name": "x", "passed": "no"}]) == []   # non-bool passed
    good = {"name": "min_tuned", "passed": False}
    assert _check_rows_list([good, {"passed": True}]) == [good]     # the valid row survives
    assert any("missing required key(s) ['name']" in r.message for r in caplog.records)


def test_check_rows_list_skips_a_none_or_blank_name(caplog):
    # `None` (the most common malformed value) is neither str nor bool, so both fields reject it by
    # type; a blank/whitespace name is a str but carries no identity, so it would surface as an
    # empty entry in failed_checks / the headline's ", "-joined names. Both are skipped.
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert _check_rows_list([{"name": None, "passed": False}]) == []
        assert _check_rows_list([{"name": "min_tuned", "passed": None}]) == []
        assert _check_rows_list([{"name": "", "passed": False}]) == []
        assert _check_rows_list([{"name": "   ", "passed": False}]) == []
    assert any("name is NoneType, not str" in r.message for r in caplog.records)
    assert any("passed is NoneType, not bool" in r.message for r in caplog.records)
    assert any("name is blank" in r.message for r in caplog.records)


def test_failed_checks_and_headline_survive_a_check_row_missing_name():
    # #1660 end to end: the reporting helpers no longer raise KeyError on a malformed row, and the
    # malformed row is excluded from both the numerator and denominator of the headline count.
    result = {"passed": False,
              "checks": [{"name": "min_tuned", "passed": False}, {"passed": False}]}
    assert failed_checks(result) == ["min_tuned"]
    assert failed_checks({"checks": [{"passed": False}]}) == []
    line = readiness_headline(result)
    assert "NOT READY" in line and "min_tuned" in line
    assert readiness_headline(
        {"passed": False, "checks": [{"name": "", "passed": False}]}
    ) == "readiness: no checks evaluated"


def test_readiness_headline_survives_non_list_checks():
    for bad in _MALFORMED_CHECKS:
        assert readiness_headline({"checks": bad, "passed": False}) == (
            "readiness: no checks evaluated"
        ), bad


def test_failed_checks_logs_warning_for_malformed_container(caplog):
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert failed_checks({"checks": 42}) == []
    assert any("checks is int" in r.message for r in caplog.records)


def test_failed_checks_logs_warning_for_skipped_rows(caplog):
    checks = [{"name": "min_tuned", "passed": False}, 42]
    with caplog.at_level(logging.WARNING, logger="benchmark.repo_set_readiness"):
        assert failed_checks({"checks": checks}) == ["min_tuned"]
    assert any("checks[1] is int" in r.message for r in caplog.records)


def test_check_readiness_does_not_mutate_the_config():
    config = json.loads(json.dumps(VALID))
    before = json.dumps(config, sort_keys=True)
    check_readiness(config)
    assert json.dumps(config, sort_keys=True) == before


def test_cli_strict_exits_nonzero_on_not_ready(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"repos": []}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(bad), "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "NOT READY" in proc.stderr


def test_cli_passes_for_curated_json():
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", CURATED_REPO_SET, "--strict"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert "READY" in proc.stderr


# --- #1698: load_config reports actionable errors instead of a raw errno / traceback ------

def test_cli_missing_config_reports_clean_error(tmp_path):
    missing = tmp_path / "does-not-exist.json"
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(missing)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "config not found" in proc.stderr
    assert str(missing) in proc.stderr


def test_cli_directory_path_reports_clean_error(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "directory" in proc.stderr or "not readable" in proc.stderr


def test_cli_oversized_int_config_reports_clean_error(tmp_path):
    # json.load raises a plain ValueError (not JSONDecodeError) on an integer literal past
    # CPython's 4300-digit limit; without the ValueError arm this dumped a raw traceback.
    huge = tmp_path / "huge.json"
    huge.write_text('{"repos": ' + "9" * 4400 + "}", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(huge)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "config is not valid JSON" in proc.stderr


def test_cli_invalid_json_config_reports_clean_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(bad)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "config is not valid JSON" in proc.stderr


def test_cli_non_object_config_reports_clean_error(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.repo_set_readiness", str(arr)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "Traceback" not in proc.stderr
    assert "config must be a JSON object" in proc.stderr


def test_load_config_is_a_directory_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import repo_set_readiness as cli

    def _raise(*args, **kwargs):
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_config(str(tmp_path / "set.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "config path is a directory, not a file" in err and "Traceback" not in err


def test_load_config_permission_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import repo_set_readiness as cli

    def _raise(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_config(str(tmp_path / "set.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "not readable" in err and "Traceback" not in err


def test_load_config_generic_os_error_is_handled(monkeypatch, tmp_path, capsys):
    from scripts import repo_set_readiness as cli

    def _raise(*args, **kwargs):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr("builtins.open", _raise)
    with pytest.raises(SystemExit) as excinfo:
        cli.load_config(str(tmp_path / "set.json"))
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "cannot read config" in err and "Traceback" not in err
