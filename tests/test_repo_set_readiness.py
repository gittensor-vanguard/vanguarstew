"""Tests for the repo-set acceptance-readiness gate (deterministic, offline)."""

import copy
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set import CURATED_REPO_SET, EXAMPLE_REPO_SET  # noqa: E402
from benchmark.repo_set_readiness import (  # noqa: E402
    DEFAULT_MIN_HELD_OUT,
    DEFAULT_MIN_TUNED,
    check_readiness,
    failed_checks,
    readiness_headline,
)

VALID = {
    "name": "ready",
    "description": "d",
    "strategy": "s",
    "repos": [
        {"name": "tuned-recent", "source": "https://github.com/org/a", "tier": "recent",
         "freeze_window": {"after": "2025-09-01", "recent_bias": True}},
        {"name": "tuned-obscure", "source": "https://github.com/org/b", "tier": "obscure",
         "freeze_window": {"min_history": 30}},
        {"name": "held-recent", "source": "https://github.com/org/c", "tier": "recent",
         "held_out": True, "freeze_window": {"after": "2025-10-01", "recent_bias": True}},
        {"name": "held-obscure", "source": "https://github.com/org/d", "tier": "obscure",
         "held_out": True, "freeze_window": {"rotation_seed": 3}},
    ],
}


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_ready_set_passes_all_checks():
    result = check_readiness(VALID)
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "min_tuned", "min_held_out", "both_tiers", "no_placeholder_sources",
    ]


def test_shipped_curated_json_passes_readiness():
    with open(CURATED_REPO_SET, encoding="utf-8") as f:
        config = json.load(f)
    result = check_readiness(config)
    assert result["passed"] is True
    assert result["repos_tuned"] >= DEFAULT_MIN_TUNED
    assert result["repos_held_out"] >= DEFAULT_MIN_HELD_OUT


def test_shipped_example_json_fails_on_placeholder_sources():
    with open(EXAMPLE_REPO_SET, encoding="utf-8") as f:
        config = json.load(f)
    result = check_readiness(config)
    assert result["passed"] is False
    assert "no_placeholder_sources" in failed_checks(result)
    assert result["checks"][0]["passed"] is True  # valid_config still passes


def test_too_few_tuned_repos_fails_min_tuned():
    config = {
        "name": "m",
        "repos": [
            {"name": "held-recent", "source": "https://github.com/org/c", "tier": "recent",
             "held_out": True, "freeze_window": {"after": "2025-10-01", "recent_bias": True}},
            {"name": "held-obscure", "source": "https://github.com/org/d", "tier": "obscure",
             "held_out": True, "freeze_window": {"rotation_seed": 3}},
            {"name": "tuned-recent", "source": "https://github.com/org/a", "tier": "recent",
             "freeze_window": {"after": "2025-09-01", "recent_bias": True}},
        ],
    }
    result = check_readiness(config, min_tuned=2)
    assert result["passed"] is False
    assert failed_checks(result) == ["min_tuned"]


def test_too_few_held_out_repos_fails_min_held_out():
    config = copy.deepcopy(VALID)
    config["repos"] = [r for r in config["repos"] if not r.get("held_out")]
    result = check_readiness(config, min_held_out=1)
    assert result["passed"] is False
    assert failed_checks(result) == ["min_held_out"]


def test_missing_tier_fails_both_tiers():
    config = copy.deepcopy(VALID)
    for repo in config["repos"]:
        repo["tier"] = "recent"
    result = check_readiness(config)
    assert result["passed"] is False
    assert failed_checks(result) == ["both_tiers"]


def test_placeholder_source_fails_no_placeholder_sources():
    config = copy.deepcopy(VALID)
    config["repos"][0]["source"] = "https://github.com/OWNER/placeholder"
    result = check_readiness(config)
    assert result["passed"] is False
    assert failed_checks(result) == ["no_placeholder_sources"]


def test_invalid_config_fails_only_valid_config():
    result = check_readiness({"repos": []})
    assert result["passed"] is False
    assert failed_checks(result) == ["valid_config"]
    assert _names(result) == ["valid_config"]


def test_non_dict_config_fails_gracefully():
    for bad in (None, "not a dict", 42, [1, 2]):
        result = check_readiness(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["valid_config"]


def test_thresholds_are_configurable():
    minimal = {
        "name": "m",
        "repos": [
            {"name": "a", "source": "https://github.com/org/a", "tier": "recent",
             "freeze_window": {"after": "2025-09-01", "recent_bias": True}},
            {"name": "b", "source": "https://github.com/org/b", "tier": "obscure",
             "freeze_window": {"min_history": 20}},
            {"name": "c", "source": "https://github.com/org/c", "tier": "recent",
             "held_out": True, "freeze_window": {"after": "2025-10-01", "recent_bias": True}},
        ],
    }
    assert check_readiness(minimal, min_tuned=1, min_held_out=1)["passed"] is True
    assert check_readiness(minimal, min_tuned=3, min_held_out=1)["passed"] is False


def test_readiness_headline_reports_ready_and_not_ready():
    ok = readiness_headline(check_readiness(VALID))
    assert "READY" in ok and "NOT" not in ok
    bad = readiness_headline(check_readiness({"repos": []}))
    assert "NOT READY" in bad


def test_check_readiness_does_not_mutate_the_config():
    config = copy.deepcopy(VALID)
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
