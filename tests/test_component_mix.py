"""Tests for component mix summary and CLI (deterministic, offline)."""

import json
import os
import sys
from unittest.mock import mock_open, patch

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.component_mix import component_mix_headline, summarize_component_mix  # noqa: E402
from scripts import component_mix as cli  # noqa: E402


def _single(judge, objective):
    return {
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": judge, "objective_mean": objective},
    }


def test_judge_fraction_from_parts():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert out["judge_fraction"] == 0.6
    assert out["objective_fraction"] == 0.4
    assert out["kind"] == "single"


def test_equal_parts_yield_half_fractions():
    out = summarize_component_mix(_single(0.5, 0.5))
    assert out["judge_fraction"] == 0.5
    assert out["objective_fraction"] == 0.5


def test_zero_sum_yields_none_fractions():
    out = summarize_component_mix(_single(0.0, 0.0))
    assert out["judge_fraction"] is None


def test_missing_parts_yield_none():
    out = summarize_component_mix({"composite_mean": 0.5})
    assert out["judge_fraction"] is None


def test_malformed_parts_yield_none():
    out = summarize_component_mix({"composite_parts": 42})
    assert out["judge_fraction"] is None


def test_non_numeric_parts_rejected():
    out = summarize_component_mix(_single("high", 0.4))
    assert out["judge_fraction"] is None


def test_bool_parts_rejected():
    out = summarize_component_mix(_single(True, 0.4))
    assert out["judge_fraction"] is None


def test_nan_parts_rejected():
    out = summarize_component_mix(_single(float("nan"), 0.4))
    assert out["judge_fraction"] is None


def test_overflowing_total_yields_none_fractions_not_fabricated_zero():
    # judge_mean and objective_mean are each individually finite, but their SUM overflows to
    # inf -- `total == 0` doesn't catch that, and dividing by inf used to silently produce a
    # fabricated 0.0/0.0 instead of failing closed like every other edge case here.
    out = summarize_component_mix(_single(1.5e308, 1.5e308))
    assert out["judge_mean"] == 1.5e308
    assert out["objective_mean"] == 1.5e308
    assert out["judge_fraction"] is None
    assert out["objective_fraction"] is None


def test_generalization_reports_both_partitions():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.4, 0.6),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "generalization"
    assert out["judge_fraction"] == 0.8
    assert out["partitions"]["tuned"]["judge_fraction"] == 0.8
    assert out["partitions"]["held_out"]["judge_fraction"] == 0.4


def test_generalization_missing_partition_parts():
    art = {
        "tuned": _single(0.7, 0.3),
        "held_out": {"composite_mean": 0.5},
        "generalization_gap": None,
    }
    out = summarize_component_mix(art)
    assert out["partitions"]["held_out"]["judge_fraction"] is None


# --- unscored placeholder must not be published as a real component score ------------------
# `run_multi_replay` reports `scored_repos: 0` with placeholder means of `0.0` (averages over
# empty lists). Masking drops those placeholders to `None`, mirroring the same `scored_repos`
# guard `component_floor._scored_metric` already applies -- while a genuinely scored run whose
# components are really `0.0` is preserved.


def test_unscored_multi_repo_placeholder_masks_means():
    art = {
        "repos": 3, "scored_repos": 0, "skipped": 3, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        "per_repo": [{"repo": "a", "tasks": 0}],
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "multi"
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None
    assert out["judge_fraction"] is None
    assert out["objective_fraction"] is None


def test_genuine_zero_scored_run_keeps_real_means():
    # Control: same 0.0 means, but scored_repos > 0 means the run really scored 0.0. It must keep
    # its real values -- proving scored_repos, not the numeric 0.0, marks the placeholder.
    art = {
        "repos": 2, "scored_repos": 2, "skipped": 0, "composite_mean": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    out = summarize_component_mix(art)
    assert out["judge_mean"] == 0.0
    assert out["objective_mean"] == 0.0


def test_single_repo_run_has_no_scored_repos_key_and_keeps_real_means():
    out = summarize_component_mix(_single(0.0, 0.0))
    assert out["judge_mean"] == 0.0
    assert out["objective_mean"] == 0.0


def test_bool_scored_repos_is_not_treated_as_an_unscored_placeholder():
    # bool is a subclass of int in Python, so `scored_repos: False` would satisfy a bare
    # `isinstance(scored, int)` check and `not False` is True -- masking would fire on a run
    # that never reported a real repo count at all. `_is_number` explicitly excludes bool
    # (`isinstance(value, bool)` check) so this artifact falls through untouched.
    art = {
        "repos": 1, "scored_repos": False,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
    }
    out = summarize_component_mix(art)
    assert out["judge_mean"] == 0.6
    assert out["objective_mean"] == 0.4


def test_float_zero_scored_repos_masks_placeholder():
    # scored_repos is documented as an int, but a hand-edited or degenerate artifact could carry
    # a float 0.0 -- _is_number accepts floats, so this must mask exactly like the int 0 case.
    art = {
        "repos": 2, "scored_repos": 0.0,
        "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
    }
    out = summarize_component_mix(art)
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None


def test_fractional_scored_repos_does_not_mask():
    # A non-zero float is truthy regardless of being fractional -- confirms masking keys off
    # falsiness, not off `scored_repos` being an int.
    art = {
        "repos": 2, "scored_repos": 0.5,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
    }
    out = summarize_component_mix(art)
    assert out["judge_mean"] == 0.6
    assert out["objective_mean"] == 0.4


def test_unscored_run_with_missing_composite_parts_does_not_crash():
    out = summarize_component_mix({"repos": 2, "scored_repos": 0, "skipped": 2})
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None


def test_unscored_run_with_malformed_composite_parts_does_not_crash():
    out = summarize_component_mix({"repos": 2, "scored_repos": 0, "composite_parts": 42})
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None


def test_generalization_masks_only_the_unscored_partition():
    art = {
        "tuned": {
            "scored_repos": 0,
            "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        },
        "held_out": {
            "scored_repos": 2,
            "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
        },
        "generalization_gap": None,
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "generalization"
    assert out["judge_mean"] is None
    assert out["partitions"]["tuned"]["judge_mean"] is None
    assert out["partitions"]["tuned"]["objective_mean"] is None
    assert out["partitions"]["held_out"]["judge_mean"] == 0.6
    assert out["partitions"]["held_out"]["objective_mean"] == 0.4


def test_generalization_masks_unscored_partition_with_missing_composite_parts():
    # The unscored partition here carries no composite_parts at all (not just a placeholder
    # 0.0) -- must still mask cleanly to None instead of falling through to a raised error, and
    # must not affect the sibling partition that did score.
    art = {
        "tuned": {"scored_repos": 0},
        "held_out": {
            "scored_repos": 2,
            "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
        },
        "generalization_gap": None,
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "generalization"
    assert out["partitions"]["tuned"]["judge_mean"] is None
    assert out["partitions"]["tuned"]["objective_mean"] is None
    assert out["partitions"]["held_out"]["judge_mean"] == 0.6
    assert out["partitions"]["held_out"]["objective_mean"] == 0.4


def test_generalization_masks_both_partitions_when_both_unscored():
    art = {
        "tuned": {
            "scored_repos": 0,
            "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        },
        "held_out": {
            "scored_repos": 0,
            "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
        },
        "generalization_gap": None,
    }
    out = summarize_component_mix(art)
    assert out["judge_mean"] is None
    assert out["objective_mean"] is None
    assert out["partitions"]["tuned"]["judge_mean"] is None
    assert out["partitions"]["held_out"]["judge_mean"] is None


def test_multi_repo_reads_top_level_parts():
    art = {
        "per_repo": [{"repo": "a", "tasks": 3}],
        "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.25},
    }
    out = summarize_component_mix(art)
    assert out["kind"] == "multi"
    assert out["judge_fraction"] == 0.75


def test_non_dict_artifact_treated_as_invalid():
    out = summarize_component_mix(None)
    assert out["kind"] == "invalid"


def test_headline_single():
    out = summarize_component_mix(_single(0.6, 0.4))
    assert "judge 60.0%" in component_mix_headline(out)


def test_headline_generalization_includes_partitions():
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.5, 0.5),
        "generalization_gap": 0.1,
    }
    out = summarize_component_mix(art)
    headline = component_mix_headline(out)
    assert "tuned 80.0%" in headline
    assert "held-out 50.0%" in headline


def test_headline_with_nan_fraction_does_not_crash():
    out = {
        "kind": "single",
        "judge_fraction": float("nan"),
        "partitions": None,
    }
    assert "n/a" in component_mix_headline(out)


@pytest.fixture
def tmp_artifact(tmp_path):
    def write(name, payload):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    return write


def test_cli_happy_path(tmp_artifact, capsys):
    path = tmp_artifact("run.json", _single(0.75, 0.25))
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["judge_fraction"] == 0.75


def test_cli_generalization_partitions(tmp_artifact, capsys):
    art = {
        "tuned": _single(0.8, 0.2),
        "held_out": _single(0.2, 0.8),
        "generalization_gap": 0.0,
    }
    path = tmp_artifact("gen.json", art)
    assert cli.run([path]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["partitions"]["held_out"]["judge_fraction"] == 0.2


def test_cli_missing_file_exits_two(capsys):
    assert cli.run(["missing.json"]) == 2
    assert "not found" in capsys.readouterr().err


def test_cli_invalid_json_exits_two(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_cli_non_object_json_exits_two(tmp_path, capsys):
    path = tmp_path / "list.json"
    path.write_text("[1]", encoding="utf-8")
    assert cli.run([str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


def test_cli_permission_error_exits_two(capsys):
    with patch("builtins.open", mock_open()) as mocked:
        mocked.side_effect = PermissionError("permission denied")
        assert cli.run(["locked.json"]) == 2
    assert "cannot read artifact" in capsys.readouterr().err
