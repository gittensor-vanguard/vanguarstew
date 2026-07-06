"""Tests for the repo-set readiness gate (deterministic, offline)."""

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.repo_set_readiness import (  # noqa: E402
    DEFAULT_MIN_TUNED,
    check_readiness,
    failed_checks,
    readiness_headline,
)


def _repo(name, tier, held_out=False, source=None):
    return {"name": name, "source": source or f"https://github.com/x/{name}",
            "tier": tier, "held_out": held_out}


def _config(repos):
    return {"name": "t", "description": "d", "strategy": "s", "repos": repos}


# A ready set: 2 tuned repos across both tiers + 1 held-out.
_READY = _config([
    _repo("a", "recent"),
    _repo("b", "obscure"),
    _repo("c", "recent", held_out=True),
])


def _names(result):
    return [c["name"] for c in result["checks"]]


def test_a_ready_repo_set_passes_every_check():
    result = check_readiness(_READY)
    assert result["passed"] is True
    assert _names(result) == [
        "valid_config", "enough_tuned", "enough_held_out", "both_tiers_present",
        "no_placeholder_sources",
    ]
    assert result["tuned_repos"] == 2 and result["held_out_repos"] == 1
    assert result["tiers"] == ["obscure", "recent"]


def test_too_few_tuned_repos_is_not_ready():
    cfg = _config([_repo("a", "recent"), _repo("b", "obscure", held_out=True)])
    result = check_readiness(cfg, min_tuned=2)
    assert result["passed"] is False
    assert "enough_tuned" in failed_checks(result)
    assert result["tuned_repos"] == 1


def test_no_held_out_repo_is_not_ready():
    cfg = _config([_repo("a", "recent"), _repo("b", "obscure")])
    result = check_readiness(cfg, min_held_out=1)
    assert result["passed"] is False
    assert "enough_held_out" in failed_checks(result)


def test_a_missing_tier_is_not_ready():
    cfg = _config([_repo("a", "recent"), _repo("b", "recent"), _repo("c", "recent", held_out=True)])
    result = check_readiness(cfg)
    assert result["passed"] is False
    assert "both_tiers_present" in failed_checks(result)
    assert result["tiers"] == ["recent"]


def test_placeholder_sources_block_readiness():
    cfg = _config([
        _repo("a", "recent", source="https://github.com/OWNER/repo-a"),
        _repo("b", "obscure"),
        _repo("c", "recent", held_out=True),
    ])
    result = check_readiness(cfg)
    assert result["passed"] is False
    assert "no_placeholder_sources" in failed_checks(result)
    assert result["placeholder_sources"] == ["https://github.com/OWNER/repo-a"]


def test_an_invalid_config_fails_only_valid_config():
    # A malformed config (unknown top-level key) fails validation; adequacy isn't assessed.
    bad = {**_READY, "reposs": []}
    result = check_readiness(bad)
    assert result["passed"] is False
    assert failed_checks(result) == ["valid_config"]
    assert len(result["checks"]) == 1
    assert result["tuned_repos"] == 0


def test_a_non_dict_config_fails_valid_config_not_crashes():
    for bad in (None, "not a dict", 42, []):
        result = check_readiness(bad)
        assert result["passed"] is False
        assert failed_checks(result) == ["valid_config"]


def test_thresholds_are_configurable():
    assert check_readiness(_READY, min_tuned=2, min_held_out=1)["passed"] is True
    assert check_readiness(_READY, min_tuned=3)["passed"] is False
    assert check_readiness(_READY, min_held_out=2)["passed"] is False


def test_the_shipped_curated_config_is_ready():
    # The curated set the acceptance run targets must itself pass the readiness gate.
    import json

    from benchmark.repo_set import CURATED_REPO_SET
    with open(CURATED_REPO_SET, "r", encoding="utf-8") as f:
        curated = json.load(f)
    result = check_readiness(curated)
    assert result["passed"] is True, failed_checks(result)


def test_headline_reports_ready_and_not_ready():
    assert "READY" in readiness_headline(check_readiness(_READY))
    not_ready = readiness_headline(check_readiness(_config([_repo("a", "recent")])))
    assert "NOT READY" in not_ready
    assert readiness_headline({}) == "readiness: no checks evaluated"
    assert DEFAULT_MIN_TUNED == 2


def test_the_shipped_example_starter_config_is_not_ready():
    # The example config ships placeholder OWNER/ sources on purpose; readiness must flag it as
    # not-ready, in contrast to the curated set — that's exactly what the gate is for.
    import json

    from benchmark.repo_set import EXAMPLE_REPO_SET
    with open(EXAMPLE_REPO_SET, "r", encoding="utf-8") as f:
        example = json.load(f)
    result = check_readiness(example)
    assert result["passed"] is False
    assert "no_placeholder_sources" in failed_checks(result)


def test_failed_checks_helper_is_robust():
    assert failed_checks({}) == []
    assert failed_checks(None) == []
    assert failed_checks("not a dict") == []
    assert failed_checks(check_readiness(_config([_repo("a", "recent")]))) != []


def test_check_readiness_does_not_mutate_the_config():
    snapshot = copy.deepcopy(_READY)
    check_readiness(_READY)
    assert _READY == snapshot
