"""Paired, local-only evaluation of a time-safe memory provider.

The normal replay score compares a candidate with an empty maintainer baseline.  That is useful
for ranking agents, but it is a weak way to establish whether *memory* helped: both variants can
beat the empty baseline while differing little from each other.  This module therefore runs the
same deterministic freeze tasks twice, alternating which arm runs first for each task, and
evaluates the paired deltas.

It deliberately does not manufacture a positive conclusion.  ``significant_improvement`` is true
only when the paired objective delta has a positive deterministic bootstrap interval *and* a
two-sided exact sign test below the configured alpha.  Live-model runs remain experiments unless
their model inputs are pinned/replayed; the statistical gate only describes the sampled tasks.
"""

from __future__ import annotations

import math
import random
import time

from benchmark.attestation import safe_memory_commitment
from benchmark.memory import combine_memory_commitments
from benchmark.runner import load_solve, run_replay
from benchmark.score import objective_component
from benchmark.taskgen import generate_tasks

ABLATION_VERSION = 2
DEFAULT_MIN_PAIRS = 6
DEFAULT_MIN_EFFECT = 0.05
DEFAULT_ALPHA = 0.05
DEFAULT_BOOTSTRAP_SAMPLES = 2_000


class AblationError(RuntimeError):
    """A paired comparison cannot make a sound conclusion."""


def _finite_number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AblationError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise AblationError(f"{field} must be a finite number")
    return number


def _row_key(row: dict) -> tuple[int, str]:
    if not isinstance(row, dict):
        raise AblationError("paired replay row is not an object")
    task = row.get("task")
    freeze = row.get("freeze")
    if isinstance(task, bool) or not isinstance(task, int) or task < 0:
        raise AblationError("paired replay row has an invalid task index")
    if not isinstance(freeze, str) or not freeze:
        raise AblationError("paired replay row has an invalid freeze commitment")
    return task, freeze


def _paired_rows(baseline_rows, memory_rows) -> list[tuple[dict, dict]]:
    if not isinstance(baseline_rows, list) or not isinstance(memory_rows, list):
        raise AblationError("paired replay artifacts must contain row lists")
    baseline = {_row_key(row): row for row in baseline_rows}
    memory = {_row_key(row): row for row in memory_rows}
    if not baseline or len(baseline) != len(baseline_rows) or len(memory) != len(memory_rows):
        raise AblationError("paired replay rows must be non-empty and unique")
    if set(baseline) != set(memory):
        raise AblationError("memory and baseline did not score the same frozen tasks")
    return [(baseline[key], memory[key]) for key in sorted(baseline)]


def exact_sign_test(deltas) -> dict:
    """Return a deterministic two-sided exact sign test for non-zero paired deltas."""
    values = [_finite_number(value, "paired delta") for value in deltas]
    positive = sum(value > 0 for value in values)
    negative = sum(value < 0 for value in values)
    nonzero = positive + negative
    if not nonzero:
        return {"positive": 0, "negative": 0, "nonzero": 0, "p_value": 1.0}
    lower = min(positive, negative)
    tail = sum(math.comb(nonzero, k) for k in range(lower + 1)) / (2 ** nonzero)
    return {
        "positive": positive,
        "negative": negative,
        "nonzero": nonzero,
        "p_value": min(1.0, round(2 * tail, 12)),
    }


def bootstrap_mean_ci(deltas, *, samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
                      seed: int = 0) -> dict:
    """Return a deterministic percentile bootstrap interval for a paired mean delta."""
    values = [_finite_number(value, "paired delta") for value in deltas]
    if not values:
        raise AblationError("bootstrap requires at least one paired delta")
    if isinstance(samples, bool) or not isinstance(samples, int) or not 100 <= samples <= 100_000:
        raise AblationError("bootstrap samples must be an integer between 100 and 100000")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise AblationError("bootstrap seed must be an integer")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(samples))

    def percentile(fraction: float) -> float:
        index = round((len(means) - 1) * fraction)
        return means[index]

    return {
        "mean": round(sum(values) / n, 6),
        "lower": round(percentile(0.025), 6),
        "upper": round(percentile(0.975), 6),
        "samples": samples,
        "seed": seed,
    }


def paired_memory_summary(baseline_rows, memory_rows, *, min_pairs: int = DEFAULT_MIN_PAIRS,
                          min_effect: float = DEFAULT_MIN_EFFECT,
                          alpha: float = DEFAULT_ALPHA,
                          bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
                          bootstrap_seed: int = 0) -> dict:
    """Summarize matched task rows and apply the predeclared memory-improvement gate."""
    if isinstance(min_pairs, bool) or not isinstance(min_pairs, int) or min_pairs < 1:
        raise AblationError("minimum paired task count must be positive")
    min_effect = _finite_number(min_effect, "minimum effect")
    alpha = _finite_number(alpha, "alpha")
    if not 0 < alpha <= 1:
        raise AblationError("alpha must be in (0, 1]")

    pairs = _paired_rows(baseline_rows, memory_rows)
    objective_deltas = [
        objective_component(memory.get("objective") or {})
        - objective_component(baseline.get("objective") or {})
        for baseline, memory in pairs
    ]
    composite_deltas = [
        _finite_number(memory.get("composite"), "memory composite")
        - _finite_number(baseline.get("composite"), "baseline composite")
        for baseline, memory in pairs
    ]
    objective_ci = bootstrap_mean_ci(
        objective_deltas, samples=bootstrap_samples, seed=bootstrap_seed
    )
    objective_sign = exact_sign_test(objective_deltas)
    composite_ci = bootstrap_mean_ci(
        composite_deltas, samples=bootstrap_samples, seed=bootstrap_seed
    )
    composite_sign = exact_sign_test(composite_deltas)
    significant = (
        len(pairs) >= min_pairs
        and objective_ci["mean"] >= min_effect
        and objective_ci["lower"] > 0
        and objective_sign["p_value"] < alpha
    )
    return {
        "pairs": len(pairs),
        "criteria": {
            "minimum_pairs": min_pairs,
            "minimum_objective_effect": min_effect,
            "alpha": alpha,
            "requires_positive_bootstrap_lower": True,
        },
        "objective_delta": {"bootstrap": objective_ci, "sign_test": objective_sign},
        "composite_delta": {"bootstrap": composite_ci, "sign_test": composite_sign},
        "significant_improvement": significant,
    }


def _latency_summary(values: list[float]) -> dict:
    """Return finite per-agent call timings without confusing setup/cache time for model time."""
    finite = [_finite_number(value, "agent elapsed time") for value in values]
    if not finite:
        return {"calls": 0, "sum_seconds": 0.0, "mean_seconds": None, "median_seconds": None}
    ordered = sorted(finite)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {
        "calls": len(finite),
        "sum_seconds": round(sum(finite), 6),
        "mean_seconds": round(sum(finite) / len(finite), 6),
        "median_seconds": round(median, 6),
    }


def _safe_run_summary(artifact: dict, elapsed_seconds: float, agent_elapsed: list[float]) -> dict:
    if not isinstance(artifact, dict):
        raise AblationError("replay artifact is not an object")
    rows = artifact.get("rows")
    if not isinstance(rows, list) or not rows:
        raise AblationError("replay produced no paired task rows")
    return {
        "tasks": artifact.get("tasks"),
        "composite_mean": artifact.get("composite_mean"),
        "objective_mean": (artifact.get("composite_parts") or {}).get("objective_mean"),
        # Whole replay time includes clone/freeze/cache effects.  Keep it for operations, but
        # use the separate agent timing below when assessing memory's runtime impact.
        "replay_elapsed_seconds": round(elapsed_seconds, 6),
        "agent_latency": _latency_summary(agent_elapsed),
        "memory_commitment": safe_memory_commitment(artifact.get("memory_commitment")),
    }


def _aggregate_arm(rows: list[dict], *, elapsed_seconds: float, agent_elapsed: list[float],
                   commitments: list[dict]) -> dict:
    """Build the minimal run-shaped aggregate needed by the paired report."""
    if not rows:
        raise AblationError("paired replay produced no rows for one arm")
    objectives = [objective_component(row.get("objective") or {}) for row in rows]
    composites = [_finite_number(row.get("composite"), "replay composite") for row in rows]
    artifact = {
        "tasks": len(rows),
        "composite_mean": round(sum(composites) / len(composites), 3),
        "composite_parts": {"objective_mean": round(sum(objectives) / len(objectives), 3)},
        "rows": rows,
        "memory_commitment": combine_memory_commitments(commitments) if commitments else None,
    }
    return _safe_run_summary(artifact, elapsed_seconds, agent_elapsed)


def run_paired_memory_ablation(repo_path, *, memory_provider, min_pairs: int = DEFAULT_MIN_PAIRS,
                                min_effect: float = DEFAULT_MIN_EFFECT,
                                alpha: float = DEFAULT_ALPHA,
                                bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
                                bootstrap_seed: int = 0, **replay_kwargs) -> dict:
    """Run no-memory and memory variants over identical task-generation arguments.

    ``memory_provider`` is supplied only to the treatment replay.  It remains subject to
    :func:`benchmark.runner.run_replay`'s benchmark-mode, public-only, freeze-time validation;
    this wrapper cannot bypass the memory boundary.
    """
    if not callable(memory_provider):
        raise TypeError("memory_provider must be callable")
    if any(name in replay_kwargs for name in ("memory_provider", "solve_fn", "tasks_override")):
        raise TypeError("memory_provider, solve_fn, and tasks_override belong to the ablation controller")

    agent_file = replay_kwargs.get("agent_file", "agent.py")
    solve = load_solve(agent_file)
    tasks = generate_tasks(
        repo_path,
        replay_kwargs.get("n_tasks", 3),
        replay_kwargs.get("horizon", 5),
        min_history=replay_kwargs.get("min_history", 10),
        recent_bias=replay_kwargs.get("recent_bias", False),
        rotation_seed=replay_kwargs.get("rotation_seed"),
        after=replay_kwargs.get("after"),
        before=replay_kwargs.get("before"),
        horizon_days=replay_kwargs.get("horizon_days"),
    )
    if not tasks:
        raise AblationError("task generation produced no time-safe pairs")
    baseline_agent_elapsed: list[float] = []
    memory_agent_elapsed: list[float] = []

    def timed_solve(timings):
        def call(**kwargs):
            started = time.monotonic()
            try:
                return solve(**kwargs)
            finally:
                timings.append(time.monotonic() - started)
        return call

    arm_rows = {"baseline": [], "memory": []}
    arm_elapsed = {"baseline": 0.0, "memory": 0.0}
    memory_commitments = []
    arm_order = {"baseline_first": 0, "memory_first": 0}
    for task_index, task in enumerate(tasks):
        # Counterbalance order by task.  A provider/model slowdown later in the run cannot be
        # mistaken for a memory benefit simply because every treatment task ran second.
        order = ("baseline", "memory") if task_index % 2 == 0 else ("memory", "baseline")
        arm_order[f"{order[0]}_first"] += 1
        for arm in order:
            started = time.monotonic()
            replay_args = {
                "repo_path": repo_path,
                "solve_fn": timed_solve(
                    baseline_agent_elapsed if arm == "baseline" else memory_agent_elapsed
                ),
                "tasks_override": [task],
                **replay_kwargs,
            }
            if arm == "memory":
                replay_args["memory_provider"] = memory_provider
            result = run_replay(
                **replay_args,
            )
            arm_elapsed[arm] += time.monotonic() - started
            rows = result.get("rows") if isinstance(result, dict) else None
            if not isinstance(rows, list) or len(rows) != 1:
                raise AblationError("one-task paired replay did not produce exactly one row")
            row = dict(rows[0])
            row["task"] = task_index
            arm_rows[arm].append(row)
            if arm == "memory":
                commitment = safe_memory_commitment(result.get("memory_commitment"))
                if commitment is None:
                    raise AblationError("memory replay did not produce a safe commitment")
                memory_commitments.append(commitment)
    paired = paired_memory_summary(
        arm_rows["baseline"], arm_rows["memory"], min_pairs=min_pairs,
        min_effect=min_effect, alpha=alpha, bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    baseline_summary = _aggregate_arm(
        arm_rows["baseline"], elapsed_seconds=arm_elapsed["baseline"],
        agent_elapsed=baseline_agent_elapsed, commitments=[],
    )
    memory_summary = _aggregate_arm(
        arm_rows["memory"], elapsed_seconds=arm_elapsed["memory"],
        agent_elapsed=memory_agent_elapsed, commitments=memory_commitments,
    )
    baseline_agent_mean = baseline_summary["agent_latency"]["mean_seconds"]
    memory_agent_mean = memory_summary["agent_latency"]["mean_seconds"]
    return {
        "version": ABLATION_VERSION,
        "mode": "paired_time_safe_memory_ablation",
        "execution": {"counterbalanced_by_task": True, **arm_order},
        "baseline": baseline_summary,
        "memory": memory_summary,
        "replay_latency_delta_seconds": round(
            arm_elapsed["memory"] - arm_elapsed["baseline"], 6
        ),
        "agent_latency_delta_seconds": (
            None if baseline_agent_mean is None or memory_agent_mean is None
            else round(memory_agent_mean - baseline_agent_mean, 6)
        ),
        "paired": paired,
    }
