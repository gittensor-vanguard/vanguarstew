"""Tests for paired, time-safe memory-ablation statistics."""

from __future__ import annotations

import pytest

import benchmark.ablation as ablation


def _row(task: int, objective: float, composite: float, freeze: str | None = None) -> dict:
    return {
        "task": task,
        "freeze": freeze or f"freeze-{task}",
        "objective": {
            "module_recall": objective,
            "actual_kinds": [],
            "release_signaled": False,
            "bump_actual": None,
        },
        "composite": composite,
    }


def test_exact_sign_test_is_two_sided_and_ignores_ties():
    result = ablation.exact_sign_test([0.1, 0.2, 0.0, -0.1])
    assert result == {"positive": 2, "negative": 1, "nonzero": 3, "p_value": 1.0}
    assert ablation.exact_sign_test([0.1] * 6)["p_value"] == 0.03125


def test_paired_summary_requires_predeclared_evidence_for_positive_claim():
    baseline = [_row(index, 0.2, 0.5) for index in range(6)]
    memory = [_row(index, 0.4, 0.58) for index in range(6)]

    result = ablation.paired_memory_summary(
        baseline, memory, min_pairs=6, min_effect=0.1, bootstrap_samples=200,
    )

    assert result["objective_delta"]["bootstrap"] == {
        "mean": 0.2,
        "lower": 0.2,
        "upper": 0.2,
        "samples": 200,
        "seed": 0,
    }
    assert result["objective_delta"]["sign_test"]["p_value"] == 0.03125
    assert result["significant_improvement"] is True


def test_paired_summary_does_not_call_a_small_or_mixed_result_significant():
    baseline = [_row(index, 0.2, 0.5) for index in range(6)]
    memory = [_row(index, 0.4 if index < 3 else 0.1, 0.58) for index in range(6)]
    result = ablation.paired_memory_summary(
        baseline, memory, min_pairs=6, min_effect=0.05, bootstrap_samples=200,
    )
    assert result["objective_delta"]["sign_test"]["p_value"] == 1.0
    assert result["significant_improvement"] is False


def test_paired_summary_fails_closed_when_freeze_tasks_do_not_match():
    with pytest.raises(ablation.AblationError, match="same frozen tasks"):
        ablation.paired_memory_summary(
            [_row(0, 0.2, 0.5, "a")], [_row(0, 0.3, 0.6, "b")],
        )


def test_paired_summary_rejects_non_finite_scores():
    with pytest.raises(ablation.AblationError, match="finite"):
        ablation.paired_memory_summary(
            [_row(0, 0.2, 0.5)], [_row(0, 0.3, float("nan"))],
        )


def test_runner_counterbalances_memory_only_for_matched_replays(monkeypatch):
    calls = []

    def fake_run_replay(**kwargs):
        calls.append(kwargs)
        improved = kwargs.get("memory_provider") is not None
        task = kwargs["tasks_override"][0]
        return {
            "tasks": 1,
            "composite_mean": 0.8 if improved else 0.5,
            "composite_parts": {"objective_mean": 0.4 if improved else 0.2},
            "rows": [_row(0, 0.4 if improved else 0.2, 0.8 if improved else 0.5,
                          task["freeze_commit"][:10])],
            "memory_commitment": {
                "memory_schema_version": 1,
                "memory_policy_version": "vanguarstew-memory-v1",
                "snapshot_root": "0" * 64,
                "query_digest": "1" * 64,
                "memory_view_digest": "2" * 64,
            } if improved else None,
        }

    monkeypatch.setattr(ablation, "run_replay", fake_run_replay)
    monkeypatch.setattr(ablation, "load_solve", lambda _path: lambda **_kwargs: {})
    monkeypatch.setattr(
        ablation,
        "generate_tasks",
        lambda *_args, **_kwargs: [
            {"freeze_commit": f"{index:040x}", "revealed": []} for index in range(6)
        ],
    )
    provider = lambda **_kwargs: {}  # noqa: E731 -- callability is the contract at this seam
    result = ablation.run_paired_memory_ablation(
        "/repo", memory_provider=provider, n_tasks=6, min_effect=0.1, bootstrap_samples=200,
    )

    assert len(calls) == 12
    assert "memory_provider" not in calls[0]
    assert calls[1]["memory_provider"] is provider
    assert calls[2]["memory_provider"] is provider
    assert "memory_provider" not in calls[3]
    assert callable(calls[0]["solve_fn"])
    assert result["execution"] == {
        "counterbalanced_by_task": True, "baseline_first": 3, "memory_first": 3,
    }
    assert result["baseline"]["memory_commitment"] is None
    assert result["agent_latency_delta_seconds"] is None
    assert result["paired"]["significant_improvement"] is True
