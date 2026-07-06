"""Offline objective-scoring golden corpus and calibration harness.

The deterministic anchor in ``benchmark.score`` (module/kind recall, release/bump match,
``objective_component``, ``composite_score``) is subtle and only covered ad hoc in
``tests/test_score.py``. This module loads a shipped corpus of named scenarios and verifies
that scoring still produces the documented values — a regression gate without git clones or
live LLM calls.

Pure evaluation: no network I/O, never mutates scenarios or the manifest, and malformed entries
fail validation rather than crashing the runner.
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmark.score import (
    base_from_releases,
    bump_level,
    changed_modules,
    commit_kind,
    composite_score,
    is_release_subject,
    kind_recall,
    module_recall,
    objective_component,
    objective_score,
    parse_semver,
    release_predicted,
    release_signaled,
    released_version,
    trajectory_overlap,
)
from benchmark.score_corpus import CORPUS_DIR, MANIFEST_PATH

_REQUIRED_SCENARIO_KEYS = frozenset({
    "id", "description", "function", "inputs", "expected",
})

_DISPATCH = {
    "module_recall": lambda inp: module_recall(inp.get("plan"), inp.get("revealed")),
    "kind_recall": lambda inp: kind_recall(inp.get("plan"), inp.get("revealed")),
    "changed_modules": lambda inp: {"modules": sorted(changed_modules(inp.get("revealed")))},
    "objective_score": lambda inp: objective_score(
        inp.get("plan"),
        inp.get("revealed"),
        version_bump=inp.get("version_bump"),
        base_version=inp.get("base_version"),
        open_issues=inp.get("open_issues"),
    ),
    "objective_component": lambda inp: {
        "objective_component": objective_component(
            objective_score(
                inp.get("plan"),
                inp.get("revealed"),
                version_bump=inp.get("version_bump"),
                base_version=inp.get("base_version"),
                open_issues=inp.get("open_issues"),
            )
        ),
    },
    "composite_score": lambda inp: {
        "composite_score": composite_score(
            inp.get("winner", "tie"),
            inp.get("objective") if isinstance(inp.get("objective"), dict) else objective_score(
                inp.get("plan"),
                inp.get("revealed"),
                version_bump=inp.get("version_bump"),
                base_version=inp.get("base_version"),
                open_issues=inp.get("open_issues"),
            ),
            w_judge=inp.get("w_judge", 0.6),
            w_objective=inp.get("w_objective", 0.4),
        ),
    },
    "is_release_subject": lambda inp: {
        "is_release_subject": is_release_subject(inp.get("text", "")),
    },
    "commit_kind": lambda inp: {"commit_kind": commit_kind(inp.get("subject", ""))},
    "bump_level": lambda inp: {
        "bump_level": bump_level(
            tuple(inp.get("old")) if isinstance(inp.get("old"), list) else inp.get("old"),
            tuple(inp.get("new")) if isinstance(inp.get("new"), list) else inp.get("new"),
        ),
    },
    "released_version": lambda inp: {
        "released_version": released_version(inp.get("revealed")),
    },
    "release_signaled": lambda inp: {
        "release_signaled": release_signaled(inp.get("revealed")),
    },
    "release_predicted": lambda inp: {
        "release_predicted": release_predicted(inp.get("plan")),
    },
    "base_from_releases": lambda inp: {
        "base_from_releases": base_from_releases(inp.get("releases")),
    },
    "parse_semver": lambda inp: {"parse_semver": parse_semver(inp.get("text", ""))},
    "trajectory_overlap": lambda inp: {
        "trajectory_overlap": trajectory_overlap(inp.get("plan"), inp.get("revealed")),
    },
}

DEFAULT_TOLERANCE = 0.001


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_scenario(data, where: str = "scenario") -> list[str]:
    """Return human-readable validation errors; an empty list means the scenario is well-formed."""
    errors = []
    if not isinstance(data, dict):
        return [f"{where}: must be a JSON object"]
    missing = sorted(_REQUIRED_SCENARIO_KEYS - set(data))
    if missing:
        errors.append(f"{where}: missing required keys {missing}")
    scenario_id = data.get("id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        errors.append(f"{where}: id must be a non-empty string")
    fn = data.get("function")
    if fn not in _DISPATCH:
        errors.append(f"{where}: unknown function {fn!r}; choose from {sorted(_DISPATCH)}")
    if "inputs" in data and not isinstance(data.get("inputs"), dict):
        errors.append(f"{where}: inputs must be an object")
    if "expected" in data and not isinstance(data.get("expected"), dict):
        errors.append(f"{where}: expected must be an object")
    return errors


def load_manifest(path: Path | None = None) -> dict:
    """Load and lightly validate the corpus manifest."""
    manifest_path = path or MANIFEST_PATH
    data = _read_json(manifest_path)
    if not isinstance(data, dict):
        raise ValueError(f"manifest must be a JSON object: {manifest_path}")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError(f"manifest.scenarios must be a non-empty list: {manifest_path}")
    for index, entry in enumerate(scenarios):
        if not isinstance(entry, dict):
            raise ValueError(f"manifest.scenarios[{index}] must be an object")
        for key in ("id", "file"):
            if not isinstance(entry.get(key), str) or not entry.get(key, "").strip():
                raise ValueError(f"manifest.scenarios[{index}] missing non-empty {key!r}")
    return data


def load_scenario(path: Path) -> dict:
    """Load one scenario file and validate it."""
    data = _read_json(path)
    errors = validate_scenario(data, where=str(path))
    if errors:
        raise ValueError("; ".join(errors))
    return data


def load_corpus(root: Path | str | None = None) -> list[dict]:
    """Load every scenario listed in the manifest under ``root`` (defaults to the shipped corpus)."""
    corpus_root = Path(root) if root is not None else CORPUS_DIR
    manifest = load_manifest(corpus_root / "manifest.json")
    scenarios_dir = corpus_root / "scenarios"
    loaded = []
    seen_ids = set()
    for entry in manifest["scenarios"]:
        scenario_path = scenarios_dir / entry["file"]
        scenario = load_scenario(scenario_path)
        if scenario["id"] != entry["id"]:
            raise ValueError(
                f"manifest id {entry['id']!r} does not match scenario file id {scenario['id']!r}"
            )
        if scenario["id"] in seen_ids:
            raise ValueError(f"duplicate scenario id {scenario['id']!r}")
        seen_ids.add(scenario["id"])
        loaded.append(scenario)
    return loaded


def _values_match(actual, expected, tolerance: float) -> bool:
    if isinstance(expected, bool):
        return actual == expected
    if expected is None:
        return actual is None
    if isinstance(expected, list) and isinstance(actual, tuple):
        actual = list(actual)
    if isinstance(expected, tuple) and isinstance(actual, list):
        expected = list(expected)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(actual) - float(expected)) <= tolerance
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return False
        if expected and isinstance(expected[0], (int, float)):
            return all(_values_match(a, e, tolerance) for a, e in zip(actual, expected))
        return actual == expected
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(k in actual and _values_match(actual[k], v, tolerance) for k, v in expected.items())
    return actual == expected


def _compare_expected(actual: dict, expected: dict, tolerance: float) -> tuple[bool, dict]:
    mismatches = {}
    for key, exp in expected.items():
        act = actual.get(key) if isinstance(actual, dict) else None
        if not _values_match(act, exp, tolerance):
            mismatches[key] = {"expected": exp, "actual": act}
    return not mismatches, mismatches


def run_scenario(scenario: dict) -> dict:
    """Replay one scenario and return expected vs actual field metadata."""
    fn_name = scenario["function"]
    inputs = scenario.get("inputs") if isinstance(scenario.get("inputs"), dict) else {}
    expected = scenario.get("expected") if isinstance(scenario.get("expected"), dict) else {}
    tolerance = scenario.get("tolerance", DEFAULT_TOLERANCE)
    try:
        tolerance = float(tolerance)
    except (TypeError, ValueError):
        tolerance = DEFAULT_TOLERANCE

    actual = _DISPATCH[fn_name](inputs)
    passed, mismatches = _compare_expected(actual, expected, tolerance)
    detail = "all expected fields match" if passed else f"mismatches: {list(mismatches)}"
    return {
        "id": scenario.get("id"),
        "description": scenario.get("description", ""),
        "tags": list(scenario.get("tags") or []) if isinstance(scenario.get("tags"), list) else [],
        "function": fn_name,
        "passed": passed,
        "mismatches": mismatches,
        "detail": detail,
    }


def check_calibration(corpus: list[dict] | None = None) -> dict:
    """Run every scenario in ``corpus`` (defaults to :func:`load_corpus`) and aggregate results."""
    scenarios = corpus if corpus is not None else load_corpus()
    results = [run_scenario(scenario) for scenario in scenarios]
    return {
        "passed": all(r["passed"] for r in results),
        "scenario_count": len(results),
        "results": results,
        "failed": [r["id"] for r in results if not r["passed"]],
    }


def failed_scenarios(result: dict) -> list[str]:
    """Scenario ids that failed calibration."""
    if not isinstance(result, dict):
        return []
    return list(result.get("failed") or [])


def calibration_headline(result: dict) -> str:
    """One-line human summary of a :func:`check_calibration` result."""
    if not isinstance(result, dict):
        return "score calibration: no scenarios evaluated"
    count = int(result.get("scenario_count") or 0)
    if count == 0:
        return "score calibration: no scenarios evaluated"
    if result.get("passed"):
        return f"score calibration: PASS ({count} scenarios)"
    failed = failed_scenarios(result)
    return f"score calibration: FAIL ({len(failed)}/{count} failed: {', '.join(failed)})"
