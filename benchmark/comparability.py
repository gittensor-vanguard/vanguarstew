"""Gate whether several replay artifacts are on the same benchmark surface.

``leaderboard`` and ``compare_eval`` rank or diff headline scores, but neither verifies that
the artifacts actually cover the same repos. Comparing a multi-repo run that scored five repos
against one that scored three different repos produces a misleading table — the numbers look
comparable but are not.

``check_comparability(artifacts)`` evaluates named criteria:

1. ``enough_artifacts`` — at least two JSON-object artifacts were supplied;
2. ``same_artifact_kind`` — every artifact is the same shape: single-repo, multi-repo
   (``per_repo``), or generalization (``tuned`` / ``held_out`` with ``generalization_gap``);
3. ``same_repo_set`` — for multi-repo artifacts, every ``per_repo`` list names the same repos;
4. ``tuned_same_repo_set`` / ``held_out_same_repo_set`` — for generalization artifacts, each
   partition's ``per_repo`` lists agree across artifacts.

Malformed ``per_repo`` containers or rows are logged and skipped when building repo signatures.

The companion ``scripts/comparability.py`` exits non-zero when the set is not comparable.

Pure evaluation: no I/O, never mutates its inputs, and a malformed/non-dict artifact simply
fails the relevant checks rather than raising.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_CHECK_ROW_KEYS = ("name", "passed")


def _is_bool(value) -> bool:
    """True for bool values including subclasses; rejects int 0/1 and other scalars."""
    return isinstance(value, bool)


def _check_rows_list(checks) -> list[dict]:
    """Return comparability gate-check rows for headline / failed_checks helpers.

    ``None`` means the key is absent. An empty list means zero checks. Both are silent.
    Non-list containers (scalars, dicts, tuples, ranges, strings, etc.) are warned and
    treated as empty (never coerced). A usable row is a dict whose ``name`` is a ``str`` and
    whose ``passed`` is a ``bool`` (subclasses allowed); anything else is skipped with a warning.
    """
    if checks is None:
        return []
    if not isinstance(checks, list):
        logger.warning(
            "comparability: checks is %s, not a list; treating as empty",
            type(checks).__name__,
        )
        return []
    rows = []
    for idx, row in enumerate(checks):
        if not isinstance(row, dict):
            logger.warning(
                "comparability: checks[%s] is %s, not an object; skipping",
                idx,
                type(row).__name__,
            )
            continue
        missing = [key for key in _CHECK_ROW_KEYS if key not in row]
        if missing:
            logger.warning(
                "comparability: checks[%s] missing required key(s) %s; skipping",
                idx,
                missing,
            )
            continue
        if not isinstance(row["name"], str):
            logger.warning(
                "comparability: checks[%s] name is %s, not str; skipping",
                idx,
                type(row["name"]).__name__,
            )
            continue
        if not _is_bool(row["passed"]):
            logger.warning(
                "comparability: checks[%s] passed is %s, not bool; skipping",
                idx,
                type(row["passed"]).__name__,
            )
            continue
        rows.append(row)
    if checks and not rows:
        logger.warning(
            "comparability: checks had %d entr%s but no usable rows",
            len(checks),
            "y" if len(checks) == 1 else "ies",
        )
    return rows


def artifact_kind(artifact) -> str:
    """Classify a replay artifact as ``single``, ``multi``, ``generalization``, or ``invalid``."""
    artifact = _dict(artifact)
    if not artifact:
        return "invalid"
    tuned, held_out = artifact.get("tuned"), artifact.get("held_out")
    if isinstance(tuned, dict) and isinstance(held_out, dict) and "generalization_gap" in artifact:
        return "generalization"
    if "per_repo" in artifact:
        return "multi"
    return "single"


def _repo_key(entry: dict) -> str:
    """Stable identity for a per-repo row (mirrors ``scripts.compare_eval``)."""
    for key in ("repo_path", "url", "repo", "name"):
        value = entry.get(key)
        if value:
            return str(value)
    freeze = entry.get("freeze_commit")
    if isinstance(freeze, str) and freeze:
        return freeze[:10]
    return repr(sorted(entry.keys()))


def _repo_keys_from_per_repo(per_repo, field: str = "per_repo") -> frozenset[str]:
    """Repo identities from a ``per_repo`` list; malformed containers yield an empty set."""
    if per_repo is None:
        return frozenset()
    if not isinstance(per_repo, list):
        logger.warning(
            "comparability: %s is %s, not a list; treating as empty",
            field,
            type(per_repo).__name__,
        )
        return frozenset()
    keys = []
    for idx, entry in enumerate(per_repo):
        if not isinstance(entry, dict):
            logger.warning(
                "comparability: %s[%s] is %s, not an object; skipping",
                field,
                idx,
                type(entry).__name__,
            )
            continue
        keys.append(_repo_key(entry))
    return frozenset(keys)


def _partition_repo_keys(artifact: dict, partition: str | None = None) -> frozenset[str]:
    """Repo keys from a multi-repo artifact or a generalization partition."""
    if partition is None:
        return _repo_keys_from_per_repo(artifact.get("per_repo"))
    part = artifact.get(partition)
    if not isinstance(part, dict):
        return frozenset()
    return _repo_keys_from_per_repo(part.get("per_repo"), f"{partition}.per_repo")


def check_comparability(artifacts) -> dict:
    """Decide whether ``artifacts`` are on the same benchmark surface.

    Returns ``{"passed": bool, "checks": [{"name", "passed", "detail"}], "artifact_kind",
    "repo_sets": {...}}``. ``passed`` is True only when every check passes.
    """
    items = artifacts if isinstance(artifacts, list) else []
    dicts = [a for a in items if isinstance(a, dict)]
    kinds = [artifact_kind(a) for a in dicts]
    kind = kinds[0] if kinds and all(k == kinds[0] for k in kinds) else None
    checks = []

    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    add("enough_artifacts", len(items) >= 2 and len(dicts) == len(items),
        f"{len(items)} artifact(s), {len(dicts)} object(s)"
        if items else "no artifacts supplied")

    same_kind = bool(kinds) and len(set(kinds)) == 1 and kinds[0] != "invalid"
    add("same_artifact_kind", same_kind,
        f"all artifacts are {kind}" if same_kind
        else f"artifact kinds differ or are invalid ({kinds!r})")

    repo_sets: dict[str, frozenset[str]] = {}
    if same_kind and kind == "multi":
        repo_sets["multi"] = _partition_repo_keys(dicts[0])
        matched = all(_partition_repo_keys(a) == repo_sets["multi"] for a in dicts)
        add("same_repo_set", matched and bool(repo_sets["multi"]),
            f"{len(repo_sets['multi'])} repo(s) in common"
            if matched and repo_sets["multi"]
            else "per_repo repo sets differ or are empty")
    elif same_kind and kind == "generalization":
        for partition in ("tuned", "held_out"):
            keys = _partition_repo_keys(dicts[0], partition)
            repo_sets[partition] = keys
            matched = all(_partition_repo_keys(a, partition) == keys for a in dicts)
            add(f"{partition}_same_repo_set", matched and bool(keys),
                f"{len(keys)} repo(s) in {partition}"
                if matched and keys
                else f"{partition} per_repo repo sets differ or are empty")
    else:
        add("same_repo_set", same_kind,
            "single-repo artifacts have no per-repo signature to compare"
            if kind == "single"
            else "repo-set comparison not applicable")

    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "artifact_kind": kind,
        "repo_sets": {name: sorted(keys) for name, keys in repo_sets.items()},
    }


def failed_checks(result: dict) -> list:
    """The names of the checks that failed in a :func:`check_comparability` result.

    Malformed ``checks`` containers and unusable rows (missing keys, wrong types) are skipped
    after logging a warning; they never raise.
    """
    return [
        c["name"] for c in _check_rows_list(_dict(result).get("checks"))
        if not c["passed"]
    ]


def comparability_headline(result: dict) -> str:
    """A one-line human summary of a :func:`check_comparability` result.

    When ``checks`` is missing, empty, a non-list container, or contains only unusable rows,
    returns ``"comparability: no checks evaluated"`` after logging any warnings.
    """
    result = _dict(result)
    checks = _check_rows_list(result.get("checks"))
    if not checks:
        return "comparability: no checks evaluated"
    kind = result.get("artifact_kind") or "unknown"
    if result.get("passed"):
        return f"comparability: COMPARABLE ({kind}, {len(checks)} check(s) passed)"
    failed = failed_checks(result)
    return (
        f"comparability: NOT COMPARABLE ({kind}, "
        f"{len(failed)}/{len(checks)} checks failed: {', '.join(failed)})"
    )
