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

Recognized artifact fields (all optional; anything missing renders ``n/a``):

- ``error``: str - present only when a run produced no scored tasks (``run_replay`` /
  ``run_multi_replay`` set it with ``tasks == 0``). Its presence takes precedence: an artifact
  carrying an ``error`` is always reported as an error, so an ambiguous ``error`` + ``tasks``
  shape is never mis-rendered as a normal run.
- ``composite_mean``: number - the headline blended score.
- ``composite_parts``: ``{"judge_mean": number, "objective_mean": number}`` - the two
  components ``composite_mean`` blends.
- ``judge_report``: ``{"wins", "losses", "ties": int, "disagreement_rate": number|None}`` -
  the canonical judge summary (produced by ``benchmark.judge.build_judge_report``). Preferred
  over ``tally``.
- ``tally``: ``{"challenger", "baseline", "tie": int}`` - the raw judge tally; used only as a
  fallback for W-L-T when ``judge_report`` is absent.
- ``per_repo``: list of ``{"repo_name"|"repo"|"repo_path": str, "tasks": int,
  "composite_mean": number}`` - one entry per replayed repo (multi-repo, or each generalization
  partition). The repo label is resolved from ``repo_name`` then ``repo`` then ``repo_path``.
- ``tuned`` / ``held_out``: multi-repo results (each of the shape above) for a generalization
  run; ``generalization_gap``: number - tuned minus held-out composite.
"""

from __future__ import annotations

_NA = "n/a"

# Default: a tuned-minus-held-out gap at or below this is reported as "holds up", above it as
# "inspect". It is only a display hint (the number itself is always shown verbatim) and is
# overridable via ``render_report(..., gap_threshold=...)``.
DEFAULT_GAP_THRESHOLD = 0.1


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


def _dict(value) -> dict:
    """``value`` when it is a dict, else an empty dict (so ``.get`` is always safe)."""
    return value if isinstance(value, dict) else {}


def artifact_kind(artifact) -> str:
    """Classify an artifact so the right renderer is chosen.

    Order matters and resolves ambiguity deterministically:

    1. a non-dict is ``unknown`` (a corrupt artifact is reported, not a crash);
    2. any artifact carrying an ``error`` is ``error`` - checked *before* the score/shape keys,
       so an ``error`` + ``tasks``/``composite_mean`` combination can't be mis-read as a run;
    3. ``tuned`` **and** ``held_out`` (both dicts) -> ``generalization``;
    4. a list ``per_repo`` -> ``multi``;
    5. a ``composite_mean`` or ``rows`` -> ``single``;
    6. otherwise ``unknown``.
    """
    if not isinstance(artifact, dict):
        return "unknown"
    if artifact.get("error"):
        return "error"
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        return "generalization"
    if isinstance(artifact.get("per_repo"), list):
        return "multi"
    if "composite_mean" in artifact or "rows" in artifact:
        return "single"
    return "unknown"


def _score_line(artifact: dict) -> str:
    parts = _dict(artifact.get("composite_parts"))
    return (
        f"- **composite_mean**: {_num(artifact.get('composite_mean'))}\n"
        f"  - judge component: {_num(parts.get('judge_mean'))}\n"
        f"  - objective anchor: {_num(parts.get('objective_mean'))}"
    )


def _judge_line(artifact: dict) -> str:
    # Prefer the canonical judge_report (build_judge_report); fall back to the raw tally only for
    # W-L-T. Both schemas are documented in the module docstring.
    report = _dict(artifact.get("judge_report"))
    tally = _dict(artifact.get("tally"))
    wins = report.get("wins", tally.get("challenger"))
    losses = report.get("losses", tally.get("baseline"))
    ties = report.get("ties", tally.get("tie"))
    return (
        f"- **judge W-L-T**: {_int(wins)}-{_int(losses)}-{_int(ties)}\n"
        f"- **order-disagreement rate**: {_pct(report.get('disagreement_rate'))}"
    )


def _repo_label(entry: dict) -> str:
    """The display name for a per-repo entry: ``repo_name`` then ``repo`` then ``repo_path``."""
    for key in ("repo_name", "repo", "repo_path"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return _NA


def _per_repo_table(per_repo) -> str:
    if not isinstance(per_repo, list) or not per_repo:
        return "_no per-repo results_"
    rows = ["| repo | tasks | composite_mean |", "| --- | ---: | ---: |"]
    for entry in per_repo:
        entry = _dict(entry)
        rows.append(
            f"| {_repo_label(entry)} | {_int(entry.get('tasks'))} | "
            f"{_num(entry.get('composite_mean'))} |"
        )
    return "\n".join(rows)


def _render_single(artifact: dict, _gap_threshold: float) -> list:
    baseline = artifact.get("baseline", _NA)
    return [
        "# Replay report - single repo",
        "",
        f"- **tasks**: {_int(artifact.get('tasks'))}",
        f"- **baseline opponent**: `{baseline}`",
        _score_line(artifact),
        _judge_line(artifact),
    ]


def _render_multi(artifact: dict, _gap_threshold: float) -> list:
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


def _render_generalization(artifact: dict, gap_threshold: float) -> list:
    lines = ["# Replay report - generalization", ""]
    gap = artifact.get("generalization_gap")
    lines.append(f"- **generalization_gap** (tuned - held-out): {_num(gap)}")
    if _is_number(gap):
        # A positive gap means the agent does worse on repos it was never tuned against. The
        # threshold is a display hint only (default DEFAULT_GAP_THRESHOLD, overridable).
        verdict = "held-out holds up" if gap <= gap_threshold else "held-out degrades - inspect"
        lines.append(f"  - {verdict} (threshold {gap_threshold:g})")
    for label in ("tuned", "held_out"):
        part = _dict(artifact.get(label))
        lines += [
            "",
            f"## {label}",
            "",
            f"- **composite_mean**: {_num(part.get('composite_mean'))} "
            f"(scored {_int(part.get('scored_repos'))} repos)",
            _per_repo_table(part.get("per_repo")),
        ]
    return lines


def _render_error(artifact: dict, _gap_threshold: float) -> list:
    return [
        "# Replay report",
        "",
        f"WARNING: the run produced no scored tasks: {artifact.get('error', 'unknown error')}",
    ]


def render_report(artifact, gap_threshold: float = DEFAULT_GAP_THRESHOLD) -> str:
    """Render ``artifact`` (any of the three run_eval shapes) as a Markdown report string.

    ``gap_threshold`` tunes only the generalization pass/inspect display hint; the gap value is
    always shown verbatim regardless.
    """
    renderer = {
        "single": _render_single,
        "multi": _render_multi,
        "generalization": _render_generalization,
        "error": _render_error,
    }.get(artifact_kind(artifact))
    if renderer is None:
        return "# Replay report\n\nWARNING: unrecognized artifact shape; nothing to report.\n"
    return "\n".join(renderer(artifact, gap_threshold)).rstrip() + "\n"
