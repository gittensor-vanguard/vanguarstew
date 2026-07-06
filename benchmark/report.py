"""Render a saved ``run_eval --out`` JSON artifact as readable Markdown.

Pure formatting: no I/O, never mutates its input, and tolerates missing or malformed fields
by rendering ``n/a`` rather than raising — so a partial or error artifact still produces a
report.
"""

from __future__ import annotations

# Tuned minus held-out above this threshold triggers an "inspect" verdict on generalization runs.
DEFAULT_GAP_INSPECT_THRESHOLD = 0.10


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt_score(value) -> str:
    return f"{float(value):.3f}" if _is_number(value) else "n/a"


def _fmt_rate(value) -> str:
    return f"{float(value):.1%}" if _is_number(value) else "n/a"


def _repo_key(entry: dict) -> str:
    for key in ("repo_name", "repo_path", "url", "repo", "name"):
        value = entry.get(key)
        if value:
            return str(value)
    freeze = entry.get("freeze_commit")
    if isinstance(freeze, str) and freeze:
        return freeze[:10]
    return "unknown"


def _looks_like_partition(part: dict) -> bool:
    return bool(part) and any(k in part for k in ("scored_repos", "composite_mean", "error"))


def _is_generalization(artifact: dict) -> bool:
    if "composite_mean" in artifact:
        return False
    if "generalization_gap" not in artifact:
        return False
    if not isinstance(artifact.get("repo_set"), str):
        return False
    tuned = artifact.get("tuned")
    held_out = artifact.get("held_out")
    if not isinstance(tuned, dict) or not isinstance(held_out, dict):
        return False
    return _looks_like_partition(tuned) and _looks_like_partition(held_out)


def _is_multi_repo(artifact: dict) -> bool:
    return isinstance(artifact.get("per_repo"), list) and "composite_mean" in artifact


def _judge_lines(artifact: dict) -> list[str]:
    report = artifact.get("judge_report")
    if not isinstance(report, dict):
        return ["- Judge W-L-T: n/a", "- Order disagreement rate: n/a"]
    wins = report.get("wins")
    losses = report.get("losses")
    ties = report.get("ties")
    if all(_is_number(v) for v in (wins, losses, ties)):
        wlt = f"{int(wins)}-{int(losses)}-{int(ties)}"
    else:
        wlt = "n/a"
    rate = _fmt_rate(report.get("disagreement_rate"))
    return [f"- Judge W-L-T: {wlt}", f"- Order disagreement rate: {rate}"]


def _composite_lines(artifact: dict) -> list[str]:
    parts = artifact.get("composite_parts")
    parts = parts if isinstance(parts, dict) else {}
    # scored_repos is only ever set by the aggregate layer (run_multi_replay / generalization
    # partitions); when it's present and zero, composite_mean is a placeholder 0.0 (nothing was
    # actually scored), not a real score -- render n/a instead of a fabricated perfect zero,
    # mirroring the same scored_repos guard in benchmark/trend.py's headline_score.
    scored = artifact.get("scored_repos")
    unscored = _is_number(scored) and not scored
    composite = None if unscored else artifact.get("composite_mean")
    judge = None if unscored else parts.get("judge_mean")
    objective = None if unscored else parts.get("objective_mean")
    lines = [f"- Composite mean: {_fmt_score(composite)}"]
    lines.append(f"- Judge mean: {_fmt_score(judge)}")
    lines.append(f"- Objective mean: {_fmt_score(objective)}")
    weights = artifact.get("weights")
    if isinstance(weights, dict):
        lines.append(
            f"- Weights: judge {_fmt_score(weights.get('judge'))}, "
            f"objective {_fmt_score(weights.get('objective'))}"
        )
    return lines


def _per_repo_table(rows: list) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return []
    header = "| Repo | Composite | Tasks |"
    sep = "| --- | ---: | ---: |"
    body = []
    for row in rows:
        if not isinstance(row, dict):
            body.append("| n/a | n/a | n/a |")
            continue
        tasks = row.get("tasks")
        tasks_txt = str(int(tasks)) if _is_number(tasks) else "n/a"
        body.append(
            f"| {_repo_key(row)} | {_fmt_score(row.get('composite_mean'))} | {tasks_txt} |"
        )
    return ["", "### Per-repo", "", header, sep, *body]


def _gap_verdict(gap, threshold: float) -> str:
    if not _is_number(gap):
        return "n/a"
    return "inspect" if float(gap) > threshold else "pass"


def _render_partition(title: str, part: dict) -> list[str]:
    lines = [f"### {title}", ""]
    if not isinstance(part, dict):
        lines.append("- Status: n/a")
        return lines
    if part.get("error"):
        lines.append(f"- Status: error ({part.get('error')})")
        return lines
    lines.extend(_composite_lines(part))
    lines.extend(_judge_lines(part))
    scored = part.get("scored_repos")
    skipped = part.get("skipped")
    if _is_number(scored):
        skip_txt = f", {int(skipped)} skipped" if _is_number(skipped) and skipped else ""
        lines.append(f"- Scored repos: {int(scored)}{skip_txt}")
    lines.extend(_per_repo_table(part.get("per_repo") or []))
    return lines


def _render_single_repo(artifact: dict) -> str:
    lines = ["# Benchmark report (single-repo)", ""]
    if artifact.get("error"):
        lines.append(f"- Status: error ({artifact.get('error')})")
    lines.extend(_composite_lines(artifact))
    lines.extend(_judge_lines(artifact))
    tasks = artifact.get("tasks")
    if _is_number(tasks):
        lines.append(f"- Tasks: {int(tasks)}")
    baseline = artifact.get("baseline")
    if baseline:
        lines.append(f"- Baseline: {baseline}")
    return "\n".join(lines) + "\n"


def _render_multi_repo(artifact: dict) -> str:
    lines = ["# Benchmark report (multi-repo)", ""]
    lines.extend(_composite_lines(artifact))
    lines.extend(_judge_lines(artifact))
    repos = artifact.get("repos")
    scored = artifact.get("scored_repos")
    skipped = artifact.get("skipped")
    if _is_number(repos):
        detail = f"{int(scored)}/{int(repos)} scored" if _is_number(scored) else str(int(repos))
        if _is_number(skipped) and skipped:
            detail += f", {int(skipped)} skipped"
        lines.append(f"- Repos: {detail}")
    lines.extend(_per_repo_table(artifact.get("per_repo") or []))
    return "\n".join(lines) + "\n"


def _render_generalization(artifact: dict, *, gap_inspect_threshold: float) -> str:
    lines = ["# Benchmark report (generalization)", ""]
    repo_set = artifact.get("repo_set")
    if isinstance(repo_set, str) and repo_set:
        lines.append(f"- Repo set: `{repo_set}`")
    gap = artifact.get("generalization_gap")
    lines.append(f"- Generalization gap (tuned − held-out): {_fmt_score(gap)}")
    lines.append(f"- Verdict: {_gap_verdict(gap, gap_inspect_threshold)}")
    lines.append("")
    lines.extend(_render_partition("Tuned", artifact.get("tuned") or {}))
    lines.append("")
    lines.extend(_render_partition("Held-out", artifact.get("held_out") or {}))
    return "\n".join(lines) + "\n"


def _render_error(artifact: dict) -> str:
    lines = ["# Benchmark report (error)", ""]
    lines.append(f"- Error: {artifact.get('error', 'n/a')}")
    tasks = artifact.get("tasks")
    if _is_number(tasks):
        lines.append(f"- Tasks: {int(tasks)}")
    return "\n".join(lines) + "\n"


def _render_unknown(artifact) -> str:
    return "# Benchmark report (unknown)\n\n- Could not recognize artifact shape.\n"


def render_report(artifact, *, gap_inspect_threshold: float = DEFAULT_GAP_INSPECT_THRESHOLD) -> str:
    """Return a Markdown summary of a replay artifact.

    Handles single-repo, multi-repo, generalization, error, and unknown shapes without raising.
    The input artifact is never mutated.
    """
    if not isinstance(artifact, dict):
        return _render_unknown(artifact)
    if _is_generalization(artifact):
        return _render_generalization(artifact, gap_inspect_threshold=gap_inspect_threshold)
    if artifact.get("error") and "composite_mean" not in artifact:
        return _render_error(artifact)
    if _is_multi_repo(artifact):
        return _render_multi_repo(artifact)
    if "composite_mean" in artifact:
        return _render_single_repo(artifact)
    if artifact.get("error"):
        return _render_error(artifact)
    return _render_unknown(artifact)
