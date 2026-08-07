"""Local, time-safe diagnostics for source-memory retrieval quality.

This evaluator is deliberately separate from agent quality scoring. It measures whether recalled,
past source paths overlap with modules that later change in the revealed window. The future window
is read only after retrieval and is never provided to the memory provider or candidate agent.
Reports contain aggregate counts and receipt-safe commitments only.
"""

from __future__ import annotations

import json
import tempfile

from benchmark.freeze import write_frozen
from benchmark.memory import (
    MemoryBoundaryError,
    combine_memory_commitments,
    memory_commitment,
    verify_memory_view,
)
from benchmark.score import changed_modules
from benchmark.taskgen import generate_tasks


class MemoryCoverageError(RuntimeError):
    """A coverage diagnostic cannot safely evaluate its inputs."""


def memory_module_coverage(view: dict, revealed) -> dict:
    """Measure source-path overlap with a revealed window without returning raw paths.

    ``revealed`` is benchmark ground truth only. This function never passes it into retrieval,
    and the returned aggregate deliberately omits module names and recalled source content.
    """
    if not verify_memory_view(view):
        raise MemoryCoverageError("coverage requires a validated memory view")
    actual = changed_modules(revealed)
    recalled_paths = []
    for item in view["items"]:
        try:
            content = json.loads(item["evidence"])
        except (TypeError, json.JSONDecodeError):
            continue
        paths = content.get("changed_paths") if isinstance(content, dict) else None
        if isinstance(paths, list):
            recalled_paths.extend(path for path in paths if isinstance(path, str))
    recalled = changed_modules([{"files": recalled_paths}])
    matched = actual & recalled
    return {
        "actual_module_count": len(actual),
        "recalled_module_count": len(recalled),
        "matched_module_count": len(matched),
        "module_coverage": round(len(matched) / len(actual), 6) if actual else None,
    }


def run_memory_coverage(repo_path: str, *, memory_provider, n_tasks: int = 6, horizon: int = 5,
                        min_history: int = 10, recent_bias: bool = False,
                        rotation_seed: int | None = None, after: str | None = None,
                        before: str | None = None, horizon_days: int | None = None) -> dict:
    """Evaluate a provider on frozen tasks without calling a model or exposing raw evidence."""
    if not callable(memory_provider):
        raise TypeError("memory_provider must be callable")
    tasks = generate_tasks(
        repo_path, n_tasks, horizon, min_history=min_history, recent_bias=recent_bias,
        rotation_seed=rotation_seed, after=after, before=before, horizon_days=horizon_days,
    )
    if not tasks:
        raise MemoryCoverageError("task generation produced no coverage tasks")
    rows, commitments = [], []
    with tempfile.TemporaryDirectory(prefix="vanguarstew_memory_coverage_") as root:
        for index, task in enumerate(tasks):
            context = write_frozen(repo_path, task["freeze_commit"], f"{root}/{index}")
            request = (
                f"plan the maintainer actions for the next {horizon_days} days"
                if horizon_days else f"plan the next {horizon} maintainer actions"
            )
            view = memory_provider(task=task, context=context, request=request, task_index=index)
            if not verify_memory_view(view):
                raise MemoryCoverageError("memory_provider returned an invalid memory view")
            if view["mode"] != "benchmark" or view["boundary"]["public_only"] is not True:
                raise MemoryBoundaryError("coverage provider crossed the benchmark memory boundary")
            rows.append(memory_module_coverage(view, task["revealed"]))
            commitments.append(memory_commitment(view))
    values = [row["module_coverage"] for row in rows if row["module_coverage"] is not None]
    return {
        "mode": "time_safe_memory_coverage",
        "tasks": len(rows),
        "coverage": {
            "scorable_tasks": len(values),
            "mean_module_coverage": round(sum(values) / len(values), 6) if values else None,
            "tasks_with_module_hit": sum(row["matched_module_count"] > 0 for row in rows),
            "total_actual_modules": sum(row["actual_module_count"] for row in rows),
            "total_matched_modules": sum(row["matched_module_count"] for row in rows),
        },
        "memory_commitment": combine_memory_commitments(commitments),
    }
