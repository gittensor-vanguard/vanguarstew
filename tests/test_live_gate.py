"""Tests for the consolidated live-decision integrity boundary."""

from benchmark import live_gate


def _artifact(tasks=3):
    objective = {
        "module_recall": 0.0,
        "weighted_module_recall": 0.0,
        "module_weights": {"core": 1},
        "weighted_matched_modules": {},
        "actual_modules": ["core"],
        "matched_modules": [],
        "kind_recall": 0.0,
        "actual_kinds": [],
        "matched_kinds": [],
        "backlog_recall": 0.0,
        "matched_issue_numbers": [],
        "addressed_issue_numbers": [],
        "addressed_backlog_diagnostics": [],
        "release_predicted": False,
        "release_signaled": False,
        "release_match": True,
        "bump_predicted": None,
        "bump_actual": None,
        "bump_match": True,
    }
    rows = [
        {
            "task": index,
            "freeze": f"{index:010x}",
            "winner": "challenger",
            "judge_order": "offline",
            "overlap": 0.0,
            "objective": objective,
            "composite": 0.6,
        }
        for index in range(tasks)
    ]
    return {
        "tasks": tasks,
        "baseline": "empty",
        "tally": {"challenger": tasks, "baseline": 0, "tie": 0},
        "decisive_margin": tasks,
        "composite_mean": 0.6,
        "composite_parts": {"judge_mean": 1.0, "objective_mean": 0.0},
        "weights": {"judge": 0.6, "objective": 0.4},
        "rows": rows,
        "judge_order_stats": {
            "agree": 0, "disagree": 0, "tie": 0, "single": 0,
            "offline": tasks, "dual_order_tasks": 0, "disagreement_rate": None,
        },
        "judge_report": {
            "wins": tasks, "losses": 0, "ties": 0, "dual_order_tasks": 0,
            "disagreements": 0, "disagreement_rate": None,
            "summary": f"judge W-L-T {tasks}-0-0; disagreement_rate=n/a (0/0 dual-order tasks)",
        },
    }


def test_exact_four_artifact_contract_and_all_gate_composition(monkeypatch):
    def passing(_artifact):
        return {"passed": True, "checks": [{"name": "ok", "passed": True}]}

    monkeypatch.setattr(live_gate, "_CHECKERS", (("stub", passing),))
    artifacts = {key: _artifact() for key in live_gate.LIVE_ARTIFACT_KEYS}
    result = live_gate.check_live_artifacts(artifacts)
    assert result["passed"] is True
    artifacts.pop("candidate_private")
    assert live_gate.check_live_artifacts(artifacts)["passed"] is False


def test_failed_checker_and_too_small_sample_fail_closed(monkeypatch):
    def failing(_artifact):
        return {"passed": False, "checks": [{"name": "bad_total", "passed": False}]}

    monkeypatch.setattr(live_gate, "_CHECKERS", (("stub", failing),))
    result = live_gate.check_live_artifact(_artifact(tasks=2))
    assert result["passed"] is False
    assert result["gates"]["stub"]["failed_checks"] == ["bad_total"]
    assert result["gates"]["sample_adequacy"]["passed"] is False


def test_real_integrity_stack_accepts_consistent_artifact():
    result = live_gate.check_live_artifact(_artifact())
    assert result["passed"] is True, result


def test_real_integrity_stack_rejects_tampered_tally():
    artifact = _artifact()
    artifact["decisive_margin"] = 2.5
    result = live_gate.check_live_artifact(artifact)
    assert result["passed"] is False
    assert result["gates"]["tally"]["passed"] is False
