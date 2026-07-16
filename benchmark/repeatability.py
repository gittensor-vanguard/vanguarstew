"""Assess whether repeated benchmark runs of the same config are stable ("re-runs are stable").

``run_replay`` is deterministic given a fixed seed, but a real acceptance run varies with
model/inference noise across repeats. ``trend`` tracks a score over *successive* runs to catch a
regression; this measures the **spread of several *repeated* runs of the same config** — is the
benchmark reproducible enough to trust a single number? (ROADMAP M1 acceptance: "re-runs are
stable.")

Given N artifacts (the repeats), ``assess_repeatability`` reports mean / stddev / min / max /
range and the **coefficient of variation** (stddev / |mean|), and calls the set *stable* when the
CV is at or below a threshold and there are enough repeats. The companion
``scripts/repeatability.py`` exits non-zero when the runs are unstable, so reproducibility can be
gated in CI the way ``--fail-under`` gates a score.

Pure analysis: no I/O, never mutates its inputs, and an artifact with no usable score is skipped
(contributes nothing) rather than raising.
"""

from __future__ import annotations

import logging
from statistics import mean, stdev

from benchmark.run_clean import check_run_clean
from benchmark.trend import headline_score

logger = logging.getLogger(__name__)

DEFAULT_MAX_CV = 0.05
DEFAULT_MIN_RUNS = 2


def _round(value):
    return round(float(value), 3) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _coerce_runs(value) -> int | None:
    """Return a non-negative run count, or ``None`` when ``value`` is not a usable integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        if value is not None:
            logger.warning(
                "repeatability: runs is %s, not a non-negative int; treating as absent",
                type(value).__name__,
            )
        return None
    return value if value >= 0 else None


def _effective_min_runs(min_runs: int) -> int:
    """Minimum scored repeats required; ``0`` means \"at least one scored run\" for gating."""
    if isinstance(min_runs, bool) or not isinstance(min_runs, int):
        return DEFAULT_MIN_RUNS
    return max(0, min_runs)


def _repeat_not_clean_detail(artifact) -> str | None:
    """Return a short reason when ``artifact`` recorded errors, else ``None``.

    Delegates to :func:`benchmark.run_clean.check_run_clean` so generalization
    repeats scan both ``tuned`` and ``held_out`` per-repo failures the same way
    the run-clean gate does.
    """
    if not isinstance(artifact, dict):
        return None
    clean = check_run_clean(artifact)
    if clean.get("passed"):
        return None
    findings = clean.get("findings")
    if isinstance(findings, list) and findings:
        return str(findings[0])
    checks = clean.get("checks")
    if isinstance(checks, list):
        for row in checks:
            if isinstance(row, dict) and not row.get("passed"):
                detail = row.get("detail")
                if detail:
                    return str(detail)
    return "recorded errors"


def _repeatability_artifacts(artifacts) -> list:
    """Return ``artifacts`` when it is a list; otherwise treat as no repeat runs.

    A truthy non-list must not reach ``for a in artifacts`` or malformed CLI /
    saved-artifact input aborts repeatability gating.
    """
    if isinstance(artifacts, list):
        return artifacts
    if artifacts is not None:
        logger.warning(
            "repeatability: artifacts is %s, not a list; treating as empty",
            type(artifacts).__name__,
        )
    return []


def assess_repeatability(artifacts, max_cv: float = DEFAULT_MAX_CV,
                         min_runs: int = DEFAULT_MIN_RUNS) -> dict:
    """Summarize the spread of repeated-run ``artifacts`` and decide whether it is stable.

    Extracts each artifact's headline composite score (via :func:`benchmark.trend.headline_score`
    — the top-level ``composite_mean``, or the ``tuned`` partition for a ``--generalization``
    artifact) and returns:

    - ``runs`` / ``scores``: how many artifacts carried a usable score, and those scores;
    - ``mean`` / ``stddev`` / ``min`` / ``max`` / ``range``: the distribution;
    - ``cv``: the coefficient of variation, ``stddev / |mean|`` — ``0.0`` when there is no spread,
      and ``None`` when the mean is 0 but the spread is not (a CV that can't be normalized);
    - ``stable``: True only when there are at least ``min_runs`` scored repeats and ``cv`` is a
      number ``<= max_cv``;
    - ``reason``: a short explanation when ``stable`` is False.
    """
    artifacts_list = _repeatability_artifacts(artifacts)
    result = {
        "stable": False,
        "runs": 0,
        "scores": [],
        "mean": None,
        "stddev": None,
        "cv": None,
        "min": None,
        "max": None,
        "range": None,
        "max_cv": max_cv,
        "min_runs": min_runs,
        "reason": "",
    }

    for idx, art in enumerate(artifacts_list):
        dirty = _repeat_not_clean_detail(art)
        if dirty is not None:
            result["reason"] = f"repeat {idx + 1} not clean: {dirty}"
            return result

    scores = [
        s for s in (headline_score(a) for a in artifacts_list)
        if s is not None
    ]
    runs = len(scores)
    result["runs"] = runs
    result["scores"] = scores

    if runs == 0:
        result["reason"] = "no scored runs"
        return result

    required = _effective_min_runs(min_runs)
    if runs < required:
        result["reason"] = f"insufficient runs: {runs} scored < min_runs {required}"
        return result

    mu = round(mean(scores), 3)
    # The repeats are a *sample* of a noisy run — the CV estimates run-to-run spread to decide
    # reproducibility, so use the sample (Bessel-corrected) standard deviation. Population stddev
    # underestimates the spread by sqrt(n/(n-1)) (~1.41x at n=2), biasing the gate too lenient.
    sd = round(stdev(scores), 3) if len(scores) > 1 else 0.0
    if sd == 0:
        cv = 0.0                       # identical runs — perfectly stable regardless of the mean
    elif mu == 0:
        cv = None                      # nonzero spread around a zero mean — can't normalize
    else:
        cv = round(sd / abs(mu), 3)

    result.update({
        "mean": mu,
        "stddev": sd,
        "cv": cv,
        "min": min(scores),
        "max": max(scores),
        "range": _round(max(scores) - min(scores)),
    })
    if cv is None:
        result["reason"] = "coefficient of variation undefined (zero mean with nonzero spread)"
    elif cv > max_cv:
        result["reason"] = f"cv {cv} exceeds max_cv {max_cv}"
    else:
        result["stable"] = True
    return result


def repeatability_headline(result: dict) -> str:
    """A one-line human summary of an :func:`assess_repeatability` result."""
    if not isinstance(result, dict):
        return "repeatability: no scored runs"
    runs = _coerce_runs(result.get("runs"))
    if runs is None or runs == 0:
        return "repeatability: no scored runs"
    min_runs = _effective_min_runs(result.get("min_runs", DEFAULT_MIN_RUNS))
    if runs < min_runs:
        return f"repeatability: inconclusive ({runs} run(s))"
    verdict = "STABLE" if result.get("stable") else "UNSTABLE"
    cv = result.get("cv")
    cv_txt = f"{cv:.1%}" if isinstance(cv, (int, float)) and not isinstance(cv, bool) else "n/a"
    return (
        f"repeatability: {verdict} over {result['runs']} runs "
        f"(mean {result.get('mean')}, cv {cv_txt})"
    )
