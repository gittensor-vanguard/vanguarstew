"""Render a saved replay artifact as a readable Markdown report.

``scripts/run_eval`` writes JSON artifacts in three shapes: a single-repo ``run_replay``
result, a multi-repo ``run_multi_replay`` aggregate, and a ``--generalization``
``run_generalization_report`` (tuned + held-out partitions plus a gap). This module turns any
of them into a compact, stable Markdown summary - headline score, judge win/loss/tie and
order-disagreement, per-repo breakdown, and (for a generalization run) the tuned-vs-held-out
gap - so a benchmark result can be *documented* and reviewed without reading raw JSON (see the
M3/M4 acceptance in ROADMAP.md).

It is pure formatting: it never mutates the artifact, performs no I/O, and tolerates missing or
malformed fields (rendered as ``n/a``) so a partial or error artifact still yields a report
instead of raising.
"""

from __future__ import annotations

_NA = "n/a"


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _num(value, places: int = 3) -> str:
    """A number rounded to ``places``, or ``n/a`` for a missing/non-numeric value."""
    return f"{round(float(value), places):.{places}f}" if _is_number(value) else _NA


def _pct(value) -> str:
    """A rate in [0, 1] as a percentage, or ``n/a``."""
    return f"{float(value):.1%}" if _is_number(value) else _NA


def _int(value) -> str:
    return str(int(value)) if _is_number(value) else _NA


def artifact_kind(artifact) -> str:
    """Classify an artifact so the right renderer is chosen.

    ``generalization`` (tuned/held-out partitions), ``multi`` (a ``per_repo`` aggregate),
    ``single`` (one repo's ``run_replay`` rows), ``error`` (a run that produced no tasks), or
    ``unknown`` for anything else - including a non-dict, so a corrupt artifact is reported, not
    a crash.
    """
    if not isinstance(artifact, dict):
        return "unknown"
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        return "generalization"
    if isinstance(artifact.get("per_repo"), list):
        return "multi"
    if artifact.get("error") and not artifact.get("tasks"):
        return "error"
    if "composite_mean" in artifact or "rows" in artifact:
        return "single"
    return "unknown"


def _score_line(artifact: dict) -> str:
    parts = artifact.get("composite_parts") if isinstance(artifact.get("composite_parts"), dict) else {}
    return (
        f"- **composite_mean**: {_num(artifact.get('composite_mean'))}\n"
        f"  - judge component: {_num(parts.get('judge_mean'))}\n"
        f"  - objective anchor: {_num(parts.get('objective_mean'))}"
    )


def _judge_line(artifact: dict) -> str:
    report = artifact.get("judge_report") if isinstance(artifact.get("judge_report"), dict) else {}
    tally = artifact.get("tally") if isinstance(artifact.get("tally"), dict) else {}
    wins = report.get("wins", tally.get("challenger"))
    losses = report.get("losses", tally.get("baseline"))
    ties = report.get("ties", tally.get("tie"))
    return (
        f"- **judge W-L-T**: {_int(wins)}-{_int(losses)}-{_int(ties)}\n"
        f"- **order-disagreement rate**: {_pct(report.get('disagreement_rate'))}"
    )


def _per_repo_table(per_repo) -> str:
    if not isinstance(per_repo, list) or not per_repo:
        return "_no per-repo results_"
    rows = ["| repo | tasks | composite_mean |", "| --- | ---: | ---: |"]
    for entry in per_repo:
        entry = entry if isinstance(entry, dict) else {}
        name = entry.get("repo_name") or entry.get("repo") or entry.get("repo_path") or _NA
        rows.append(f"| {name} | {_int(entry.get('tasks'))} | {_num(entry.get('composite_mean'))} |")
    return "\n".join(rows)


def _render_single(artifact: dict) -> list:
    baseline = artifact.get("baseline", _NA)
    return [
        "# Replay report - single repo",
        "",
        f"- **tasks**: {_int(artifact.get('tasks'))}",
        f"- **baseline opponent**: `{baseline}`",
        _score_line(artifact),
        _judge_line(artifact),
    ]


def _render_multi(artifact: dict) -> list:
    return [
        "# Replay report - multi-repo",
        "",
        f"- **repos**: {_int(artifact.get('repos'))} "
        f"(scored {_int(artifact.get('scored_repos'))}, skipped {_int(artifact.get('skipped'))})",
        _score_line(artifact),
        _judge_line(artifact),
        "",
        "## Per-repo",
        "",
        _per_repo_table(artifact.get("per_repo")),
    ]


def _render_generalization(artifact: dict) -> list:
    lines = ["# Replay report - generalization", ""]
    gap = artifact.get("generalization_gap")
    lines.append(f"- **generalization_gap** (tuned - held-out): {_num(gap)}")
    if _is_number(gap):
        # A positive gap means the agent does worse on repos it was never tuned against.
        verdict = "held-out holds up" if gap <= 0.1 else "held-out degrades - inspect"
        lines.append(f"  - {verdict}")
    for label in ("tuned", "held_out"):
        part = artifact.get(label) if isinstance(artifact.get(label), dict) else {}
        lines += [
            "",
            f"## {label}",
            "",
            f"- **composite_mean**: {_num(part.get('composite_mean'))} "
            f"(scored {_int(part.get('scored_repos'))} repos)",
            _per_repo_table(part.get("per_repo")),
        ]
    return lines


def _render_error(artifact: dict) -> list:
    return [
        "# Replay report",
        "",
        f"WARNING: the run produced no scored tasks: {artifact.get('error', 'unknown error')}",
    ]


def render_report(artifact) -> str:
    """Render ``artifact`` (any of the three run_eval shapes) as a Markdown report string."""
    kind = artifact_kind(artifact)
    renderer = {
        "single": _render_single,
        "multi": _render_multi,
        "generalization": _render_generalization,
        "error": _render_error,
    }.get(kind)
    if renderer is None:
        return "# Replay report\n\nWARNING: unrecognized artifact shape; nothing to report.\n"
    return "\n".join(renderer(artifact)).rstrip() + "\n"
