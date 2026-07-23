"""Rank several replay artifacts against each other — the "pick the best" view.

``compare_eval`` diffs *two* artifacts and ``trend`` tracks *one* score over successive runs.
This is the third N-way operation: given several artifacts (e.g. one per candidate agent, or one
per configuration) evaluated on the same benchmark, rank them by their headline composite score
and show how far each trails the best. That is the benchmark's ultimate question — *which
candidate wins* — made explicit and reproducible instead of eyeballed across files.

Each artifact's comparable score is extracted with :func:`benchmark.trend.headline_score` (the
top-level ``composite_mean``, or the ``tuned`` partition for a ``--generalization`` artifact), so
ranking stays consistent with the trend view. Standard competition ranking is used: equal scores
share a rank and the next rank skips accordingly (1, 2, 2, 4). Artifacts with no usable score are
never ranked — they are reported separately in ``unscored`` — so a partial/malformed entry can't
silently win or crash the board.

Pure analysis: no I/O, and it never mutates its inputs.
"""

from __future__ import annotations

import logging
import math

from benchmark.trend import headline_score

logger = logging.getLogger(__name__)


def _is_number(value) -> bool:
    """Only a finite, non-boolean int/float counts as numeric.

    A saved artifact round-trips ``NaN``/``Infinity`` verbatim through ``json``, so a non-finite
    ``composite_parts`` mean must degrade to ``None`` in a leaderboard row rather than surfacing as
    an ``inf``/``nan`` component — mirroring ``component_mix``, ``composite_spread`` (#1397), and
    ``trend`` (#1183). ``OverflowError`` guards an oversized int that cannot convert to float.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, OverflowError):
        return False


def _round(value):
    return round(float(value), 3) if _is_number(value) else None


_EMPTY_COMPONENTS = {
    "judge_mean": None,
    "objective_mean": None,
    "module_recall_mean": None,
    "kind_recall_mean": None,
    "release_accuracy": None,
    "bump_accuracy": None,
}


def _components(artifact) -> dict:
    """The judge/objective component means, plus the M7 foresight breakdown, behind an
    artifact's headline score.

    Reads ``composite_parts`` and ``foresight`` from the headline partition — the top level for
    single/multi-repo artifacts, or ``tuned`` for a ``--generalization`` artifact — so a
    leaderboard row can show *why* an entry ranks where it does: not just the blended
    ``objective_mean``, but whether that came from getting the modules, the commit-kinds, or the
    releases right. Missing/malformed parts yield ``None`` components; an artifact saved before
    the foresight breakdown existed degrades the same way.
    """
    if not isinstance(artifact, dict):
        return dict(_EMPTY_COMPONENTS)
    partition = artifact
    if isinstance(artifact.get("tuned"), dict) and isinstance(artifact.get("held_out"), dict):
        partition = artifact["tuned"]
    parts = partition.get("composite_parts") if isinstance(partition.get("composite_parts"), dict) else {}
    foresight = partition.get("foresight") if isinstance(partition.get("foresight"), dict) else {}
    return {
        "judge_mean": _round(parts.get("judge_mean")),
        "objective_mean": _round(parts.get("objective_mean")),
        "module_recall_mean": _round(foresight.get("module_recall_mean")),
        "kind_recall_mean": _round(foresight.get("kind_recall_mean")),
        "release_accuracy": _round(foresight.get("release_accuracy")),
        "bump_accuracy": _round(foresight.get("bump_accuracy")),
    }


def _leaderboard_entries(entries) -> list:
    """Return ``entries`` when it is a list; otherwise treat as no candidates.

    A truthy non-list must not reach ``for label, artifact in entries`` or malformed CLI /
    saved-artifact input aborts leaderboard ranking (#532).
    """
    if isinstance(entries, list):
        return entries
    if entries is not None:
        logger.warning(
            "leaderboard: entries is %s, not a list; treating as empty",
            type(entries).__name__,
        )
    return []


def _leaderboard_point(entry, index=None):
    """Return a ``(label, artifact)`` pair from an entry, or ``None`` to skip it.

    Entries come from the same malformed CLI / saved-artifact input the container guard covers
    (#532). A non-pair entry — not a list/tuple, or the wrong length (including a ``bytes`` value,
    which is not a ``(label, artifact)`` pair even though it is iterable) — is skipped rather than
    crashing the ``label, artifact`` unpacking. The warning names the offending index and its
    actual content so a bad saved leaderboard can be pinpointed, matching how the module already
    logs a non-list ``entries`` / ``unscored``.
    """
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return entry[0], entry[1]
    where = f"entries[{index}]" if index is not None else "a leaderboard entry"
    logger.warning(
        "leaderboard: %s is not a (label, artifact) pair (%s: %s); skipping",
        where, type(entry).__name__, repr(entry)[:120],
    )
    return None


def rank(entries) -> dict:
    """Rank an iterable of ``(label, artifact)`` by headline composite score, best first.

    Returns a stable summary:

    - ``ranking``: ``{rank, label, composite_mean, delta_from_best, judge_mean, objective_mean,
      module_recall_mean, kind_recall_mean, release_accuracy, bump_accuracy}`` for every
      *scored* entry, highest score first. ``rank`` is competition-ranked (ties share a rank);
      ``delta_from_best`` is ``composite_mean - best`` (``0.0`` for the leader, negative for the
      rest). Ties keep the input order. The last four fields are the M7 foresight breakdown (see
      ``_components``) — the legible, independently-checkable axes behind ``objective_mean``,
      ``None`` when an axis had no applicable tasks or the artifact predates the breakdown.
    - ``best``: ``{label, composite_mean}`` of the top entry, or ``None`` if nothing scored.
    - ``unscored``: labels of entries with no usable score (never ranked).
    - ``scored`` / ``total``: how many entries carried a usable score, and how many were given.
    """
    scored = []       # (index, label, score, components) — index keeps ties in input order
    unscored = []
    for index, entry in enumerate(_leaderboard_entries(entries)):
        pair = _leaderboard_point(entry, index)
        if pair is None:
            continue
        label, artifact = pair
        score = headline_score(artifact)
        if score is None:
            unscored.append(label)
        else:
            scored.append((index, label, score, _components(artifact)))

    # Highest score first; ties broken by original input order (the kept index) for stability.
    scored.sort(key=lambda item: (-item[2], item[0]))

    best_score = scored[0][2] if scored else None
    ranking = []
    for position, (_index, label, score, components) in enumerate(scored):
        # Competition ranking: a tie with the previous entry shares its rank; otherwise the rank
        # is 1-based position (so ranks skip after a tie: 1, 2, 2, 4).
        if position > 0 and score == scored[position - 1][2]:
            rank_value = ranking[-1]["rank"]
        else:
            rank_value = position + 1
        ranking.append({
            "rank": rank_value,
            "label": label,
            "composite_mean": score,
            "delta_from_best": _round(score - best_score),
            "judge_mean": components["judge_mean"],
            "objective_mean": components["objective_mean"],
            "module_recall_mean": components["module_recall_mean"],
            "kind_recall_mean": components["kind_recall_mean"],
            "release_accuracy": components["release_accuracy"],
            "bump_accuracy": components["bump_accuracy"],
        })

    return {
        "ranking": ranking,
        "best": {"label": scored[0][1], "composite_mean": best_score} if scored else None,
        "unscored": unscored,
        "scored": len(scored),
        "total": len(scored) + len(unscored),
    }


def _leaderboard_unscored(unscored) -> list:
    """Return ``unscored`` when it is a list; otherwise treat as no unscored labels."""
    if isinstance(unscored, list):
        return unscored
    if unscored is not None:
        logger.warning(
            "leaderboard: summary unscored is %s, not a list; treating as empty",
            type(unscored).__name__,
        )
    return []


def leaderboard_headline(summary: dict) -> str:
    """A one-line human summary of a :func:`rank` result."""
    if not isinstance(summary, dict) or not summary.get("scored"):
        return "leaderboard: no scored artifacts"
    best = summary.get("best") or {}
    runners = summary["scored"] - 1
    tail = f" over {runners} other(s)" if runners > 0 else ""
    unscored = len(_leaderboard_unscored(summary.get("unscored")))
    unscored_txt = f"; {unscored} unscored" if unscored else ""
    return (
        f"leaderboard: {best.get('label')} leads at "
        f"{best.get('composite_mean')}{tail}{unscored_txt}"
    )
