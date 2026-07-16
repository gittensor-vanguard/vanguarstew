"""Tests for replay artifact comparison helpers."""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.compare_eval import (  # noqa: E402
    _is_generalization,
    _repo_key,
    compare_eval_artifacts,
    comparison_headline,
    load_artifact,
)


def test_compare_eval_artifacts_reports_composite_and_part_deltas():
    baseline = {
        "composite_mean": 0.5,
        "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
        "judge_report": {
            "wins": 1,
            "losses": 2,
            "ties": 0,
            "disagreement_rate": 0.25,
        },
    }
    candidate = {
        "composite_mean": 0.7,
        "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.5},
        "judge_report": {
            "wins": 2,
            "losses": 1,
            "ties": 0,
            "disagreement_rate": 0.5,
        },
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_mean"]["delta"] == 0.2
    assert diff["composite_parts"]["judge_mean"]["delta"] == 0.2
    assert diff["composite_parts"]["objective_mean"]["delta"] == 0.1
    assert diff["judge_report"]["wins"]["delta"] == 1
    assert diff["judge_report"]["disagreement_rate"]["delta"] == 0.25


def test_oversized_int_composite_mean_is_unavailable_not_a_crash():
    # json parses an arbitrarily long integer literal into a Python int; float() raises
    # OverflowError for one too large to convert, so an oversized composite_mean must degrade to
    # unavailable rather than crashing the comparison (mirrors repo_task_mean #1571).
    big = 10 ** 400
    diff = compare_eval_artifacts({"composite_mean": 0.5}, {"composite_mean": big})
    assert diff["composite_mean"]["baseline"] == 0.5
    assert diff["composite_mean"]["candidate"] is None
    assert diff["composite_mean"]["delta"] is None


def test_unscored_candidate_masks_composite_parts_like_composite_mean():
    # An all-skipped run (scored_repos: 0) reports composite_mean AND composite_parts as
    # placeholder 0.0 means. composite_mean is masked to None; the parts must be too, or the diff
    # self-contradicts (a None composite delta beside a fabricated component drop).
    baseline = {"composite_mean": 0.8, "scored_repos": 3,
                "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.35}}
    candidate = {"composite_mean": 0.0, "scored_repos": 0,
                 "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}}
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_mean"] == {"baseline": 0.8, "candidate": None, "delta": None}
    assert diff["composite_parts"]["judge_mean"] == {"baseline": 0.8, "candidate": None, "delta": None}
    assert diff["composite_parts"]["objective_mean"] == {"baseline": 0.35, "candidate": None, "delta": None}


def test_unscored_baseline_masks_its_own_composite_parts():
    baseline = {"composite_mean": 0.0, "scored_repos": 0,
                "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}}
    candidate = {"composite_mean": 0.7, "scored_repos": 3,
                 "composite_parts": {"judge_mean": 0.8, "objective_mean": 0.5}}
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_parts"]["judge_mean"] == {"baseline": None, "candidate": 0.8, "delta": None}


def test_both_unscored_reports_no_component_section():
    art = {"composite_mean": 0.0, "scored_repos": 0,
           "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0}}
    diff = compare_eval_artifacts(dict(art), dict(art))
    assert "composite_parts" not in diff   # nothing scored on either side -> no component deltas
    assert diff["composite_mean"] == {"baseline": None, "candidate": None, "delta": None}


def test_masking_is_scoped_to_placeholder_means_not_real_judge_counts():
    # Masking applies only to the unscored placeholder MEANS (composite_mean/composite_parts). The
    # judge_report COUNTS are real integers (zero judged tasks -> zero wins is a true zero, not a
    # placeholder mean), so they are reported as-is, not masked.
    baseline = {"composite_mean": 0.5, "scored_repos": 2,
                "composite_parts": {"judge_mean": 0.6, "objective_mean": 0.4},
                "judge_report": {"wins": 3, "losses": 0}}
    candidate = {"composite_mean": 0.0, "scored_repos": 0,
                 "composite_parts": {"judge_mean": 0.0, "objective_mean": 0.0},
                 "judge_report": {"wins": 0, "losses": 0}}
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_parts"]["judge_mean"]["candidate"] is None      # placeholder mean -> masked
    assert diff["judge_report"]["wins"] == {"baseline": 3, "candidate": 0, "delta": -3}  # real count


def test_compare_eval_artifacts_handles_missing_optional_fields():
    diff = compare_eval_artifacts({"composite_mean": 0.4}, {"composite_mean": 0.3})
    assert diff == {"composite_mean": {"baseline": 0.4, "candidate": 0.3, "delta": -0.1}}
    assert "judge_report" not in diff
    assert "per_repo" not in diff


def test_compare_eval_artifacts_treats_non_finite_scores_as_unavailable():
    nan = float("nan")
    inf = float("inf")
    diff = compare_eval_artifacts({"composite_mean": 0.5}, {"composite_mean": nan})
    assert diff["composite_mean"] == {"baseline": 0.5, "candidate": None, "delta": None}
    assert comparison_headline(diff) == "compare_eval: composite_mean delta unavailable"

    diff = compare_eval_artifacts({"composite_mean": nan}, {"composite_mean": 0.5})
    assert diff["composite_mean"]["baseline"] is None
    assert diff["composite_mean"]["candidate"] == 0.5
    assert diff["composite_mean"]["delta"] is None

    diff = compare_eval_artifacts({"composite_mean": inf}, {"composite_mean": -inf})
    assert diff["composite_mean"] == {"baseline": None, "candidate": None, "delta": None}

    diff = compare_eval_artifacts(
        {"composite_mean": 0.5, "judge_report": {"disagreement_rate": nan}},
        {"composite_mean": 0.6, "judge_report": {"disagreement_rate": 0.25}},
    )
    assert diff["judge_report"]["disagreement_rate"]["candidate"] == 0.25
    assert diff["judge_report"]["disagreement_rate"]["baseline"] is None
    assert diff["judge_report"]["disagreement_rate"]["delta"] is None


def test_compare_eval_json_output_stays_finite():
    diff = compare_eval_artifacts({"composite_mean": 0.5}, {"composite_mean": float("nan")})
    encoded = json.dumps(diff)
    assert "NaN" not in encoded
    assert json.loads(encoded) == diff


def test_compare_eval_artifacts_reports_per_repo_deltas():
    baseline = {
        "composite_mean": 0.5,
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.4, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.6, "tasks": 2},
        ],
    }
    candidate = {
        "composite_mean": 0.55,
        "per_repo": [
            {"repo_path": "/a", "composite_mean": 0.5, "tasks": 2},
            {"repo_path": "/b", "composite_mean": 0.6, "tasks": 3},
        ],
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert len(diff["per_repo"]) == 2
    by_repo = {row["repo"]: row for row in diff["per_repo"]}
    assert by_repo["/a"]["composite_mean"]["delta"] == 0.1
    assert by_repo["/b"]["composite_mean"]["delta"] == 0.0


def test_compare_eval_artifacts_tolerates_non_list_per_repo():
    # A malformed artifact whose per_repo is not a list must not crash the diff (#464); it is
    # treated as an empty repo table, so the top-level composite_mean still diffs.
    for bad in (42, True, {"repo_path": "/a"}, "rows"):
        diff = compare_eval_artifacts({"per_repo": bad, "composite_mean": 0.5},
                                      {"per_repo": [], "composite_mean": 0.6})
        assert diff["composite_mean"]["delta"] == 0.1
        assert "per_repo" not in diff
        # symmetric: a non-list on the candidate side is equally tolerated
        diff = compare_eval_artifacts({"per_repo": [], "composite_mean": 0.5},
                                      {"per_repo": bad, "composite_mean": 0.6})
        assert diff["composite_mean"]["delta"] == 0.1
        assert "per_repo" not in diff


def test_compare_eval_artifacts_skips_non_dict_per_repo_rows():
    # A non-dict row inside the per_repo list is skipped, while well-formed rows still diff.
    baseline = {"composite_mean": 0.5, "per_repo": ["junk", {"repo_path": "/a",
                                                             "composite_mean": 0.4, "tasks": 2}]}
    candidate = {"composite_mean": 0.55, "per_repo": [{"repo_path": "/a",
                                                       "composite_mean": 0.5, "tasks": 2}, 99]}
    diff = compare_eval_artifacts(baseline, candidate)
    assert [row["repo"] for row in diff["per_repo"]] == ["/a"]
    assert diff["per_repo"][0]["composite_mean"]["delta"] == 0.1


def test_comparison_headline_describes_direction():
    diff = {"composite_mean": {"baseline": 0.4, "candidate": 0.55, "delta": 0.15}}
    assert "up +0.150" in comparison_headline(diff)


def test_load_artifact_reads_json_file(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"composite_mean": 0.42}), encoding="utf-8")
    assert load_artifact(str(path))["composite_mean"] == 0.42


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "scripts.compare_eval", *args],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


def test_cli_reports_a_clean_error_for_a_missing_file(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"composite_mean": 0.5}), encoding="utf-8")
    missing = tmp_path / "does-not-exist.json"
    result = _run_cli(str(good), str(missing))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(missing) in result.stderr


def test_cli_reports_a_clean_error_for_a_non_object_artifact(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"composite_mean": 0.5}), encoding="utf-8")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    result = _run_cli(str(good), str(bad))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "must be a JSON object" in result.stderr


def test_cli_reports_a_clean_error_for_invalid_json(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"composite_mean": 0.5}), encoding="utf-8")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not valid json", encoding="utf-8")
    result = _run_cli(str(good), str(invalid))
    assert result.returncode == 1
    assert "Traceback" not in result.stderr


def test_cli_still_compares_well_formed_artifacts(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"composite_mean": 0.5}), encoding="utf-8")
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({"composite_mean": 0.6}), encoding="utf-8")
    result = _run_cli(str(baseline), str(candidate))
    assert result.returncode == 0
    assert "compare_eval" in result.stderr
    diff = json.loads(result.stdout)
    assert diff["composite_mean"]["baseline"] == 0.5
    assert diff["composite_mean"]["candidate"] == 0.6


def test_repo_key_handles_explicit_null_freeze_commit():
    assert _repo_key({"freeze_commit": None}) == repr(sorted(["freeze_commit"]))


def test_compare_eval_artifacts_matches_rows_with_null_freeze_commit():
    baseline = {
        "composite_mean": 0.5,
        "per_repo": [{"freeze_commit": None, "composite_mean": 0.4, "tasks": 1}],
    }
    candidate = {
        "composite_mean": 0.6,
        "per_repo": [{"freeze_commit": None, "composite_mean": 0.5, "tasks": 1}],
    }
    diff = compare_eval_artifacts(baseline, candidate)
    assert len(diff["per_repo"]) == 1
    row = diff["per_repo"][0]
    assert row["repo"] == repr(sorted(["composite_mean", "freeze_commit", "tasks"]))
    assert row["composite_mean"]["delta"] == 0.1


# --- #382: diff generalization-shaped artifacts (tuned/held_out partitions + gap) ---------

def _gen(tuned=0.5, held=0.4, gap=0.1, tuned_scored=2, held_scored=1):
    return {
        "repo_set": "foo.json",
        "tuned": {"composite_mean": tuned, "scored_repos": tuned_scored},
        "held_out": {"composite_mean": held, "scored_repos": held_scored},
        "generalization_gap": gap,
    }


def test_is_generalization_detector_is_strict():
    assert _is_generalization(_gen()) is True
    # A standard artifact is never misread, even with a stray scalar 'tuned'/'held_out'.
    assert _is_generalization({"composite_mean": 0.5}) is False
    assert _is_generalization({"tuned": 0.5, "held_out": 0.4}) is False   # scalars, not dicts
    assert _is_generalization({"tuned": {"composite_mean": 0.5}}) is False  # held_out missing
    assert _is_generalization({
        "tuned": {"composite_mean": 0.5, "scored_repos": 1},
        "held_out": {"composite_mean": 0.4, "scored_repos": 1},
    }) is False  # missing generalization_gap and repo_set
    assert _is_generalization({
        "composite_mean": 0.5,
        "tuned": {"composite_mean": 0.9},
        "held_out": {"composite_mean": 0.1},
    }) is False  # standard replay wins over partition keys


def test_compare_eval_ignores_incomplete_generalization_shape():
    artifact = {
        "tuned": {"composite_mean": 0.5, "scored_repos": 1},
        "held_out": {"composite_mean": 0.4, "scored_repos": 1},
    }
    diff = compare_eval_artifacts(artifact, artifact)
    assert diff == {
        "composite_mean": {"baseline": None, "candidate": None, "delta": None},
    }
    assert "generalization" not in diff


def test_compare_eval_ignores_partition_keys_on_standard_artifacts():
    baseline = {
        "composite_mean": 0.5,
        "tuned": {"composite_mean": 0.9},
        "held_out": {"composite_mean": 0.1},
    }
    candidate = {"composite_mean": 0.6}
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_mean"]["delta"] == 0.1
    assert "generalization" not in diff


def test_compare_eval_diffs_generalization_partitions_and_gap():
    diff = compare_eval_artifacts(_gen(0.5, 0.4, 0.1), _gen(0.6, 0.45, 0.15))
    gen = diff["generalization"]
    assert gen["tuned"]["composite_mean"]["delta"] == 0.1
    assert gen["held_out"]["composite_mean"]["delta"] == 0.05
    assert gen["generalization_gap"]["delta"] == 0.05
    # the standard top-level composite_mean triplet is replaced, not emitted as all-None
    assert "composite_mean" not in diff


def test_generalization_diff_tolerates_missing_and_none_partition_scores():
    # A partition that only recorded an error (no composite_mean) diffs to None, no crash.
    baseline = {"repo_set": "foo.json",
                "tuned": {"error": "no tuned repos", "scored_repos": 0},
                "held_out": {"composite_mean": 0.4, "scored_repos": 1},
                "generalization_gap": None}
    candidate = {"repo_set": "foo.json",
                 "tuned": {"composite_mean": None, "scored_repos": 0},
                 "held_out": {"composite_mean": 0.5, "scored_repos": 1},
                 "generalization_gap": None}
    diff = compare_eval_artifacts(baseline, candidate)
    gen = diff["generalization"]
    assert gen["tuned"]["composite_mean"]["delta"] is None
    assert gen["held_out"]["composite_mean"]["delta"] == 0.1
    assert gen["generalization_gap"]["delta"] is None


def test_generalization_diff_treats_placeholder_zero_on_unscored_partition_as_unavailable():
    # scored_repos: 0 carries composite_mean: 0.0 as a placeholder — not a real score.
    baseline = {"repo_set": "foo.json",
                "tuned": {"composite_mean": 0.0, "scored_repos": 0},
                "held_out": {"composite_mean": 0.5, "scored_repos": 1},
                "generalization_gap": None}
    candidate = {"repo_set": "foo.json",
                 "tuned": {"composite_mean": 0.6, "scored_repos": 1},
                 "held_out": {"composite_mean": 0.5, "scored_repos": 1},
                 "generalization_gap": 0.1}
    diff = compare_eval_artifacts(baseline, candidate)
    gen = diff["generalization"]
    assert gen["tuned"]["composite_mean"] == {
        "baseline": None,
        "candidate": 0.6,
        "delta": None,
    }
    assert "tuned +0.600" not in comparison_headline(diff)
    assert "tuned n/a" in comparison_headline(diff)


def test_compare_eval_treats_unscored_multi_repo_placeholder_as_unavailable():
    baseline = {"composite_mean": 0.0, "scored_repos": 0, "repos": 2, "skipped": 2}
    candidate = {"composite_mean": 0.6, "scored_repos": 2, "repos": 2, "skipped": 0}
    diff = compare_eval_artifacts(baseline, candidate)
    assert diff["composite_mean"] == {"baseline": None, "candidate": 0.6, "delta": None}


def test_mixed_shapes_fall_back_to_standard_without_crashing():
    # Only one side is generalization-shaped -> not treated as a generalization diff.
    diff = compare_eval_artifacts(_gen(), {"composite_mean": 0.6})
    assert "generalization" not in diff
    assert "composite_mean" in diff          # standard path
    assert diff["composite_mean"]["baseline"] is None   # generalization side has no top-level mean


def test_comparison_headline_describes_generalization_diff():
    diff = compare_eval_artifacts(_gen(0.5, 0.4, 0.1), _gen(0.6, 0.45, 0.15))
    line = comparison_headline(diff)
    assert "tuned +0.100" in line
    assert "held_out +0.050" in line
    assert "gap +0.050" in line


def test_comparison_headline_generalization_marks_unavailable_delta():
    diff = compare_eval_artifacts(
        {"repo_set": "foo.json",
         "tuned": {"composite_mean": None, "scored_repos": 0},
         "held_out": {"composite_mean": 0.4, "scored_repos": 1},
         "generalization_gap": None},
        {"repo_set": "foo.json",
         "tuned": {"composite_mean": None, "scored_repos": 0},
         "held_out": {"composite_mean": 0.5, "scored_repos": 1},
         "generalization_gap": None},
    )
    line = comparison_headline(diff)
    assert "tuned n/a" in line and "gap n/a" in line and "held_out +0.100" in line
