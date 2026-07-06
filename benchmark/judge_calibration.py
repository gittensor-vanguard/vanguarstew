"""Offline pairwise-judge golden corpus and calibration harness.

The deterministic offline judge (``_offline_rank`` / substance heuristics) is the backbone of
``VANGUARSTEW_OFFLINE=1`` replay, but its intended ranking behavior is only covered ad hoc in
``tests/test_judge.py``. This module loads a shipped corpus of named scenarios and verifies
that ``pairwise_judge`` still ranks them as documented — a regression gate for judge substance
rules without git clones or live LLM calls.

Pure evaluation: no network I/O, never mutates scenarios or the manifest, and malformed entries
fail validation rather than crashing the runner.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from agent.llm import LLM
from benchmark.judge import judge_verbose, pairwise_judge
from benchmark.judge_corpus import CORPUS_DIR, MANIFEST_PATH

logger = logging.getLogger(__name__)

_REQUIRED_SCENARIO_KEYS = frozenset({
    "id", "description", "context", "revealed", "submission_a", "submission_b", "expected_winner",
})
_VALID_WINNERS = frozenset({"A", "B", "tie"})


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
    winner = data.get("expected_winner")
    if winner not in _VALID_WINNERS:
        errors.append(f"{where}: expected_winner must be one of {sorted(_VALID_WINNERS)}, got {winner!r}")
    for key in ("context", "revealed", "submission_a", "submission_b"):
        if key in data and not isinstance(data.get(key), (dict, list, str, int, float, bool, type(None))):
            errors.append(f"{where}: {key} has an unsupported type {type(data.get(key)).__name__}")
    scenario_id = data.get("id")
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        errors.append(f"{where}: id must be a non-empty string")
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


def run_scenario(scenario: dict, llm: LLM | None = None) -> dict:
    """Replay one scenario and return expected vs actual winner metadata."""
    llm = llm or LLM(api_key="offline")
    context = scenario.get("context") if isinstance(scenario.get("context"), dict) else {}
    revealed = scenario.get("revealed")
    submission_a = scenario.get("submission_a")
    submission_b = scenario.get("submission_b")
    expected = scenario.get("expected_winner")
    actual = pairwise_judge(context, submission_a, submission_b, revealed, llm)
    _, judge_order = judge_verbose(
        context, submission_a, submission_b, revealed, llm, dual_order=False,
    )
    passed = actual == expected
    return {
        "id": scenario.get("id"),
        "description": scenario.get("description", ""),
        "tags": list(scenario.get("tags") or []) if isinstance(scenario.get("tags"), list) else [],
        "expected_winner": expected,
        "actual_winner": actual,
        "judge_order": judge_order,
        "passed": passed,
        "detail": (
            f"expected {expected}, got {actual} ({judge_order})"
            if not passed
            else f"winner {actual} ({judge_order})"
        ),
    }


def check_symmetry(scenario: dict, llm: LLM | None = None) -> dict | None:
    """When ``expect_symmetric`` is true, verify swapping A/B flips the decisive winner."""
    if not scenario.get("expect_symmetric"):
        return None
    llm = llm or LLM(api_key="offline")
    context = scenario.get("context") if isinstance(scenario.get("context"), dict) else {}
    revealed = scenario.get("revealed")
    forward = pairwise_judge(
        context, scenario.get("submission_a"), scenario.get("submission_b"), revealed, llm,
    )
    backward = pairwise_judge(
        context, scenario.get("submission_b"), scenario.get("submission_a"), revealed, llm,
    )
    if forward == "tie" and backward == "tie":
        passed = True
    elif forward in ("A", "B") and backward in ("A", "B"):
        passed = forward != backward
    else:
        passed = False
    return {
        "id": scenario.get("id"),
        "forward": forward,
        "backward": backward,
        "passed": passed,
        "detail": f"forward={forward}, backward={backward}",
    }


def check_calibration(corpus: list[dict] | None = None, llm: LLM | None = None) -> dict:
    """Run every scenario in ``corpus`` (defaults to :func:`load_corpus`) and aggregate results."""
    scenarios = corpus if corpus is not None else load_corpus()
    llm = llm or LLM(api_key="offline")
    results = [run_scenario(scenario, llm) for scenario in scenarios]
    symmetry = []
    for scenario in scenarios:
        sym = check_symmetry(scenario, llm)
        if sym is not None:
            symmetry.append(sym)
    winner_checks = [r for r in results]
    symmetry_passed = all(s["passed"] for s in symmetry) if symmetry else True
    winners_passed = all(r["passed"] for r in winner_checks)
    return {
        "passed": winners_passed and symmetry_passed,
        "scenario_count": len(results),
        "results": results,
        "symmetry_checks": symmetry,
        "failed": [r["id"] for r in results if not r["passed"]]
               + [s["id"] for s in symmetry if not s["passed"]],
    }


def _failed_ids_list(failed) -> list[str]:
    """Return scenario ids from a calibration ``failed`` list; skip junk rows."""
    if not isinstance(failed, list):
        if failed is not None:
            logger.warning(
                "judge_calibration: failed is %s, not a list; treating as empty",
                type(failed).__name__,
            )
        return []
    ids = []
    for idx, item in enumerate(failed):
        if not isinstance(item, str) or not item.strip():
            logger.warning(
                "judge_calibration: failed[%s] is not a usable scenario id; skipping",
                idx,
            )
            continue
        ids.append(item.strip())
    if failed and not ids:
        logger.warning(
            "judge_calibration: failed list had %d entr%s but no usable scenario ids",
            len(failed),
            "y" if len(failed) == 1 else "ies",
        )
    return ids


_SYMMETRY_ROW_KEYS = ("id", "passed")

_NUMPY_BOOL_TYPENAMES = frozenset({"bool_", "bool8"})


def _is_passed(value) -> bool:
    """Accept native ``bool`` and numpy scalar booleans; reject int 0/1 and other scalars.

    Uses ``type(value) is bool`` rather than ``isinstance`` so arbitrary bool subclasses
    (which can override ``__bool__``) are not treated as symmetry pass/fail flags.
    """
    if type(value) is bool:
        return True
    return type(value).__name__ in _NUMPY_BOOL_TYPENAMES


def _check_symmetry_row_field(key: str, value) -> bool:
    """Return whether ``value`` is usable for a symmetry row ``key`` in ``_SYMMETRY_ROW_KEYS``."""
    if key == "id":
        return isinstance(value, str) and bool(value.strip())
    if key == "passed":
        return _is_passed(value)
    return False


def _symmetry_checks_list(checks) -> list[dict]:
    """Return symmetry-check rows for :func:`calibration_headline`.

    ``None`` means the key is absent. An empty list means zero symmetry checks. Both are silent.
    Non-list containers are warned and treated as empty (never coerced). A usable row is a dict
    with every key in ``_SYMMETRY_ROW_KEYS``: ``id`` must be a non-empty ``str`` and ``passed``
    must be a native ``bool`` or numpy scalar boolean; anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "judge_calibration: symmetry_checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "judge_calibration: symmetry_checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _SYMMETRY_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "judge_calibration: symmetry_checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        bad_key = None
        for key in _SYMMETRY_ROW_KEYS:
            if not _check_symmetry_row_field(key, row[key]):
                bad_key = key
                break
        if bad_key is not None:
            value = row[bad_key]
            if bad_key == "id":
                detail = (
                    type(value).__name__
                    if not isinstance(value, str)
                    else "empty str"
                )
                expected = "non-empty str"
            else:
                detail = type(value).__name__
                expected = "bool"
            logger.warning(
                "judge_calibration: symmetry_checks[%s] %s is %s, not a usable %s; skipping",
                idx,
                bad_key,
                detail,
                expected,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "judge_calibration: symmetry_checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def failed_scenarios(result: dict) -> list[str]:
    """Scenario ids that failed winner or symmetry checks."""
    if not isinstance(result, dict):
        return []
    return _failed_ids_list(result.get("failed"))


def calibration_headline(result: dict) -> str:
    """One-line human summary of a :func:`check_calibration` result."""
    if not isinstance(result, dict):
        return "calibration: no scenarios evaluated"
    count = int(result.get("scenario_count") or 0)
    if count == 0:
        return "calibration: no scenarios evaluated"
    if result.get("passed"):
        sym = _symmetry_checks_list(result.get("symmetry_checks"))
        extra = f" + {len(sym)} symmetry" if sym else ""
        return f"calibration: PASS ({count} scenarios{extra})"
    failed = failed_scenarios(result)
    return f"calibration: FAIL ({len(failed)}/{count} failed: {', '.join(failed)})"
