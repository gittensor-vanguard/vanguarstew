"""Offline objective-scoring golden corpus and calibration harness.

Scoring rules in :mod:`benchmark.score` are subtle (file-weighted module recall, kind-only
guards, release/bump axes, backlog diagnostics excluded from ranking). This module loads a
shipped corpus of named scenarios and verifies that ``objective_score`` / ``objective_component``
/ ``composite_score`` still produce the documented values — a regression gate for the M2 anchor
without git clones or live LLM calls.

Pure evaluation: no network I/O, never mutates scenarios or the manifest, and malformed entries
fail validation rather than crashing the runner.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from benchmark.score import composite_score, objective_component, objective_score
from benchmark.score_corpus import CORPUS_DIR, MANIFEST_PATH

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE = 0.001

_REQUIRED_SCENARIO_KEYS = frozenset({"id", "description", "plan", "revealed", "expected"})


def _read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_scenario(data, where: str = "scenario") -> list[str]:
    """Return human-readable validation errors; an empty list means the scenario is well-formed."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{where}: must be a JSON object"]
    missing = sorted(_REQUIRED_SCENARIO_KEYS - set(data))
    if missing:
        errors.append(f"{where}: missing required keys {missing}")
    scenario_id = data.get("id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        errors.append(f"{where}: id must be a non-empty string")
    expected = data.get("expected")
    if not isinstance(expected, dict) or not expected:
        errors.append(f"{where}: expected must be a non-empty object")
    if "plan" in data and not isinstance(data.get("plan"), list):
        errors.append(f"{where}: plan must be a list")
    if "revealed" in data and not isinstance(data.get("revealed"), list):
        errors.append(f"{where}: revealed must be a list")
    winner = data.get("winner")
    if winner is not None and winner not in {"A", "tie", "B"}:
        errors.append(f"{where}: winner must be one of ['A', 'B', 'tie'], got {winner!r}")
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
    loaded: list[dict] = []
    seen_ids: set[str] = set()
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


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _values_match(expected, actual, tolerance: float) -> bool:
    if isinstance(expected, bool):
        return expected is actual
    if _is_number(expected) and _is_number(actual):
        return abs(float(expected) - float(actual)) <= tolerance
    return expected == actual


def _score_kwargs(scenario: dict) -> dict:
    kwargs: dict = {}
    if "open_issues" in scenario:
        kwargs["open_issues"] = scenario.get("open_issues")
    if "base_version" in scenario:
        kwargs["base_version"] = scenario.get("base_version")
    if "version_bump" in scenario:
        kwargs["version_bump"] = scenario.get("version_bump")
    return kwargs


def _actual_fields(scenario: dict, objective: dict) -> dict:
    actual = dict(objective)
    actual["objective_component"] = objective_component(objective)
    winner = scenario.get("winner")
    if winner in {"A", "tie", "B"}:
        w_judge = scenario.get("w_judge", 0.6)
        w_objective = scenario.get("w_objective", 0.4)
        actual["composite_score"] = composite_score(
            winner, objective, w_judge, w_objective,
        )
    return actual


def run_scenario(scenario: dict, tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Replay one scenario and return expected vs actual score metadata."""
    expected = scenario.get("expected") if isinstance(scenario.get("expected"), dict) else {}
    objective = objective_score(
        scenario.get("plan"),
        scenario.get("revealed"),
        **_score_kwargs(scenario),
    )
    actual_fields = _actual_fields(scenario, objective)
    mismatches = []
    for key, exp in expected.items():
        act = actual_fields.get(key)
        if not _values_match(exp, act, tolerance):
            mismatches.append(f"{key}: expected {exp!r}, got {act!r}")
    passed = not mismatches
    return {
        "id": scenario.get("id"),
        "description": scenario.get("description", ""),
        "tags": list(scenario.get("tags") or []) if isinstance(scenario.get("tags"), list) else [],
        "expected": expected,
        "actual": {key: actual_fields.get(key) for key in expected},
        "passed": passed,
        "detail": "; ".join(mismatches) if mismatches else "all expected fields matched",
    }


def check_calibration(corpus: list[dict] | None = None,
                      tolerance: float = DEFAULT_TOLERANCE) -> dict:
    """Run every scenario in ``corpus`` (defaults to :func:`load_corpus`) and aggregate results."""
    scenarios = corpus if corpus is not None else load_corpus()
    results = [run_scenario(scenario, tolerance) for scenario in scenarios]
    return {
        "passed": all(r["passed"] for r in results),
        "scenario_count": len(results),
        "results": results,
        "failed": [r["id"] for r in results if not r["passed"]],
        "tolerance": tolerance,
    }


def _failed_ids_list(failed) -> list[str]:
    if not isinstance(failed, list):
        if failed is not None:
            logger.warning(
                "score_calibration: failed is %s, not a list; treating as empty",
                type(failed).__name__,
            )
        return []
    return [item for item in failed if isinstance(item, str) and item.strip()]


def failed_scenarios(result: dict) -> list[str]:
    """Scenario ids that failed calibration."""
    if not isinstance(result, dict):
        return []
    return _failed_ids_list(result.get("failed"))


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
