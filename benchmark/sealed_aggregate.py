"""A narrow, canonical result envelope for sealed multi-repository evaluation.

The ordinary replay artifact contains repository identities, task rows, diagnostics, paths, and
model outputs.  None of those fields are safe to copy blindly across a sealed-workload boundary.
This module constructs a new envelope from an allowlist of aggregate scalars; it never attempts to
sanitize the original artifact in place.

The envelope is a transport contract, not an attestation claim.  A Polaris sandbox boot receipt
proves the TDX boot and customer-key binding, but does not bind code uploaded later over SSH or this
result.  Callers must keep that distinction explicit.
"""

from __future__ import annotations

import hmac
import json
import math
import re
from decimal import Decimal, InvalidOperation

SEALED_AGGREGATE_CONTRACT = "sealed-aggregate-v1"
_CHALLENGE_RE = re.compile(r"[0-9a-f]{64}")
_ENVELOPE_KEYS = {
    "challenge",
    "composite_micros",
    "contract",
    "judge_micros",
    "objective_micros",
    "scored_repos",
    "skipped_repos",
}
_SCORE_KEYS = ("composite_micros", "judge_micros", "objective_micros")


class SealedAggregateError(ValueError):
    """A source artifact or sealed aggregate failed the fixed output contract."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _count(value, label: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SealedAggregateError(f"{label} must be an integer")
    minimum = 1 if positive else 0
    if not minimum <= value <= 1_000_000:
        raise SealedAggregateError(f"{label} is outside the allowed range")
    return value


def _score_micros(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SealedAggregateError(f"{label} must be a finite score")
    try:
        if not math.isfinite(value):
            raise SealedAggregateError(f"{label} must be a finite score")
        decimal = Decimal(str(value))
    except (InvalidOperation, OverflowError, ValueError) as exc:
        raise SealedAggregateError(f"{label} must be a finite score") from exc
    if not Decimal(0) <= decimal <= Decimal(1):
        raise SealedAggregateError(f"{label} is outside the score range")
    micros = decimal * Decimal(1_000_000)
    if micros != micros.to_integral_value():
        raise SealedAggregateError(f"{label} has more than six decimal places")
    return int(micros)


def _challenge(value: str) -> str:
    if not isinstance(value, str) or not _CHALLENGE_RE.fullmatch(value):
        raise SealedAggregateError("challenge must be 32 random bytes encoded as lowercase hex")
    return value


def build_sealed_aggregate(artifact, *, challenge: str) -> str:
    """Return canonical JSON containing only fixed aggregate scalars from ``artifact``."""
    if not isinstance(artifact, dict):
        raise SealedAggregateError("evaluation artifact must be an object")
    parts = artifact.get("composite_parts")
    if not isinstance(parts, dict):
        raise SealedAggregateError("evaluation artifact is missing composite parts")
    envelope = {
        "contract": SEALED_AGGREGATE_CONTRACT,
        "challenge": _challenge(challenge),
        "scored_repos": _count(artifact.get("scored_repos"), "scored_repos", positive=True),
        "skipped_repos": _count(artifact.get("skipped"), "skipped"),
        "composite_micros": _score_micros(artifact.get("composite_mean"), "composite_mean"),
        "judge_micros": _score_micros(parts.get("judge_mean"), "judge_mean"),
        "objective_micros": _score_micros(parts.get("objective_mean"), "objective_mean"),
    }
    return _canonical_json(envelope)


def verify_sealed_aggregate(stdout, *, expected_challenge: str) -> dict:
    """Fail closed on extra fields, non-canonical JSON, replay, or malformed scalar values."""
    checks = {
        "json_object": False,
        "exact_schema": False,
        "canonical_json": False,
        "contract_version": False,
        "challenge_binding": False,
        "counts": False,
        "scores": False,
    }
    try:
        challenge = _challenge(expected_challenge)
    except SealedAggregateError:
        challenge = ""
    try:
        envelope = json.loads(stdout) if isinstance(stdout, str) else None
    except (ValueError, TypeError):
        envelope = None
    if not isinstance(envelope, dict):
        return {"ok": False, "checks": checks, "detail": "sealed aggregate is not a JSON object"}

    checks["json_object"] = True
    checks["exact_schema"] = set(envelope) == _ENVELOPE_KEYS
    checks["canonical_json"] = _canonical_json(envelope) == stdout
    checks["contract_version"] = envelope.get("contract") == SEALED_AGGREGATE_CONTRACT
    received_challenge = envelope.get("challenge")
    checks["challenge_binding"] = (
        bool(challenge)
        and isinstance(received_challenge, str)
        and bool(_CHALLENGE_RE.fullmatch(received_challenge))
        and hmac.compare_digest(received_challenge, challenge)
    )
    try:
        _count(envelope.get("scored_repos"), "scored_repos", positive=True)
        _count(envelope.get("skipped_repos"), "skipped_repos")
        checks["counts"] = True
    except SealedAggregateError:
        pass
    checks["scores"] = all(
        isinstance(envelope.get(key), int)
        and not isinstance(envelope.get(key), bool)
        and 0 <= envelope[key] <= 1_000_000
        for key in _SCORE_KEYS
    )
    ok = all(checks.values())
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "ok": ok,
        "checks": checks,
        "detail": "sealed aggregate contract passed" if ok else "; ".join(failed),
    }
