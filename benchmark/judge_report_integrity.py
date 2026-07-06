"""Gate whether a replay artifact's judge summary matches its underlying signals.

``run_replay`` rolls pairwise outcomes into ``judge_report`` (wins/losses/ties, disagreement
telemetry) sourced from ``tally`` and ``judge_order_stats``. ``judge_gate`` checks whether the
judge was *robust enough to trust*, but nothing verifies the summary fields actually agree with
the raw tallies and order-sensitivity counters. A hand-edited artifact could report a low
``disagreement_rate`` while the underlying stats tell a different story.

``check_judge_report_integrity(result)`` verifies, for each scored replay slice:

1. ``report_present`` — ``judge_report`` is a dict when judge telemetry is expected;
2. ``stats_present`` — ``judge_order_stats`` is a dict alongside the report;
3. ``wins_match_tally`` / ``losses_match_tally`` / ``ties_match_tally`` — when ``tally`` is
   present, report W-L-T counts match;
4. ``dual_order_tasks_match`` — ``dual_order_tasks`` agrees with ``judge_order_stats``;
5. ``disagreements_match`` — report ``disagreements`` equals the stats ``disagree`` count;
6. ``disagreement_rate_matches`` — ``disagreement_rate`` equals ``disagree / dual_order_tasks``.

Multi-repo and ``--generalization`` artifacts are checked per scored partition or ``per_repo``
entry.

The companion ``scripts/judge_report_integrity.py`` exits non-zero when the summary is
inconsistent.

Pure evaluation: no I/O, never mutates the result; malformed/non-dict input fails with explicit
checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TALLY_KEYS = ("challenger", "baseline", "tie")
_REPORT_TALLY = ("wins", "losses", "ties")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _checks_list(checks) -> list:
    if isinstance(checks, list):
        return checks
    if checks is not None:
        logger.warning(
            "judge_report_integrity: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
    return []


def _per_repo_list(items, field: str = "per_repo") -> list:
    if items is None:
        return []
    if not isinstance(items, list):
        logger.warning(
            "judge_report_integrity: %s is %s, not a list; treating as empty",
            field, type(items).__name__,
        )
        return []
    return [entry for entry in items if isinstance(entry, dict)]


def _tally_counts(tally: dict) -> dict | None:
    if not isinstance(tally, dict):
        return None
    counts = {}
    for key in _TALLY_KEYS:
        value = tally.get(key)
        if not _is_number(value):
            return None
        counts[key] = int(value)
    return counts


def _stats_dual_order_tasks(stats: dict) -> int | None:
    dual = stats.get("dual_order_tasks")
    if _is_number(dual):
        return int(dual)
    parts = [stats.get(key) for key in ("agree", "disagree", "tie")]
    if all(_is_number(part) for part in parts):
        return int(sum(parts))
    return None


def _expected_disagreement_rate(stats: dict) -> float | None:
    dual = _stats_dual_order_tasks(stats)
    disagree = stats.get("disagree")
    if dual and dual > 0 and _is_number(disagree):
        return round(float(disagree) / dual, 3)
    return None


def _slice_has_judge_telemetry(slice_: dict) -> bool:
    tasks = slice_.get("tasks")
    if _is_number(tasks) and int(tasks) > 0:
        return True
    if slice_.get("judge_report") is not None or slice_.get("judge_order_stats") is not None:
        return True
    scored = slice_.get("scored_repos")
    return _is_number(scored) and int(scored) > 0


def _expand_slice(label: str, part: dict) -> list[tuple[str, dict]]:
    if part.get("judge_report") is not None or part.get("judge_order_stats") is not None:
        return [(label, part)]
    slices = []
    for index, entry in enumerate(_per_repo_list(part.get("per_repo"))):
        if _slice_has_judge_telemetry(entry):
            slices.append((f"{label}:repo-{index}", entry))
    return slices


def _report_slices(result: dict) -> list[tuple[str, dict]]:
    tuned, held_out = result.get("tuned"), result.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in result:
        slices: list[tuple[str, dict]] = []
        for label, part in (("tuned", tuned), ("held_out", held_out)):
            if isinstance(part, dict) and part.get("scored_repos"):
                slices.extend(_expand_slice(label, part))
        return slices
    if "per_repo" in result:
        return [
            (f"repo-{index}", entry)
            for index, entry in enumerate(_per_repo_list(result.get("per_repo")))
            if _slice_has_judge_telemetry(entry)
        ]
    if _slice_has_judge_telemetry(result):
        return [("run", result)]
    return []


def _check_slice(label: str, slice_: dict, checks: list) -> None:
    prefix = f"{label}:" if label != "run" else ""

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({
            "name": f"{prefix}{name}" if prefix else name,
            "passed": bool(passed),
            "detail": detail,
        })

    report = slice_.get("judge_report")
    stats = slice_.get("judge_order_stats")
    tally = _tally_counts(slice_.get("tally"))

    report_ok = isinstance(report, dict)
    stats_ok = isinstance(stats, dict)
    add("report_present", report_ok,
        "judge_report present" if report_ok else f"judge_report missing ({report!r})")
    add("stats_present", stats_ok,
        "judge_order_stats present" if stats_ok else f"judge_order_stats missing ({stats!r})")

    if report_ok and tally is not None:
        mapping = dict(zip(_REPORT_TALLY, _TALLY_KEYS))
        for report_key, tally_key in mapping.items():
            report_value = report.get(report_key)
            expected = tally[tally_key]
            ok = _is_number(report_value) and int(report_value) == expected
            add(f"{report_key}_match_tally", ok,
                f"report {report_key} {report_value} vs tally {tally_key} {expected}")
    elif report_ok:
        for report_key in _REPORT_TALLY:
            add(f"{report_key}_match_tally", True, f"no tally to compare for {report_key}")

    if report_ok and stats_ok:
        expected_dual = _stats_dual_order_tasks(stats)
        report_dual = report.get("dual_order_tasks")
        add("dual_order_tasks_match",
            expected_dual is not None and _is_number(report_dual)
            and int(report_dual) == expected_dual,
            f"report dual_order_tasks {report_dual} vs stats {expected_dual}")

        disagree = stats.get("disagree")
        report_disagreements = report.get("disagreements")
        add("disagreements_match",
            _is_number(disagree) and _is_number(report_disagreements)
            and int(report_disagreements) == int(disagree),
            f"report disagreements {report_disagreements} vs stats disagree {disagree}")

        expected_rate = _expected_disagreement_rate(stats)
        report_rate = report.get("disagreement_rate")
        if expected_rate is None and report_rate is None:
            add("disagreement_rate_matches", True, "no dual-order tasks; rate n/a")
        elif expected_rate is not None and _is_number(report_rate):
            add("disagreement_rate_matches", float(report_rate) == expected_rate,
                f"report rate {report_rate} vs expected {expected_rate}")
        else:
            add("disagreement_rate_matches", False,
                f"cannot compare disagreement_rate ({report_rate!r} vs {expected_rate!r})")
    elif report_ok:
        add("dual_order_tasks_match", False, "cannot compare without judge_order_stats")
        add("disagreements_match", False, "cannot compare without judge_order_stats")
        add("disagreement_rate_matches", False, "cannot compare without judge_order_stats")


def check_judge_report_integrity(result) -> dict:
    """Evaluate a run ``result`` against judge-report integrity criteria."""
    checks: list[dict] = []

    if not isinstance(result, dict):
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": f"artifact must be a JSON object, got {type(result).__name__}",
        })
        return {"passed": False, "checks": checks}

    slices = _report_slices(result)
    if not slices:
        checks.append({
            "name": "artifact_shape",
            "passed": False,
            "detail": "no scored replay slice with judge telemetry to verify",
        })
    else:
        for label, slice_ in slices:
            _check_slice(label, slice_, checks)

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


def failed_checks(result: dict) -> list[str]:
    """The names of the checks that failed in a :func:`check_judge_report_integrity` result."""
    return [
        c["name"] for c in _checks_list(_dict(result).get("checks"))
        if isinstance(c, dict) and not c.get("passed")
    ]


def integrity_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_judge_report_integrity` result."""
    result = _dict(result)
    checks = _checks_list(result.get("checks"))
    if not checks:
        return "judge report integrity: no checks evaluated"
    if result.get("passed"):
        return f"judge report integrity: CONSISTENT ({len(checks)} checks passed)"
    failed = failed_checks(result)
    return (f"judge report integrity: INCONSISTENT ({len(failed)}/{len(checks)} checks failed: "
            f"{', '.join(failed)})")
