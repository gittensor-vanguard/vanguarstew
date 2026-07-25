"""Fail-closed, offline Intel TDX/DCAP verification for Polaris receipts.

The cryptographic work is delegated to the optional ``dcap-qvl`` Python package.  This module
deliberately exposes no collateral-fetching helper: supplying a quote must never cause an implicit
network request or disclose quote-derived platform identifiers.  Operators pass a complete,
previously acquired ``QuoteCollateralV3`` JSON object and an explicit measurement policy.

Polaris currently returns a cache bundle containing Intel response bodies.  That bundle omits the
issuer-chain response headers required by an independent verifier, so it is detected and rejected
as incomplete rather than silently supplemented over the network.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

_POLICY_VERSION = 1
_MEASUREMENT_FIELDS = ("mr_td", "rt_mr0", "rt_mr1", "rt_mr2")
_OPTIONAL_MEASUREMENT_FIELDS = ("rt_mr3", "mr_config_id", "mr_owner", "mr_owner_config")
_MEASUREMENT_RE = re.compile(r"[0-9a-f]{96}")
_MAX_COLLATERAL_BYTES = 8 * 1024 * 1024
_QVL_COLLATERAL_FIELDS = frozenset(
    {
        "pck_crl_issuer_chain",
        "root_ca_crl",
        "pck_crl",
        "tcb_info_issuer_chain",
        "tcb_info",
        "tcb_info_signature",
        "qe_identity_issuer_chain",
        "qe_identity",
        "qe_identity_signature",
    }
)


class DcapVerificationError(ValueError):
    """An invalid local policy or collateral object."""


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _measurement_values(value, *, field: str) -> frozenset[str]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, (list, tuple, set, frozenset)) or not values:
        raise DcapVerificationError(f"{field} must contain at least one measurement")
    normalized = frozenset(str(item).lower() for item in values)
    if not all(_MEASUREMENT_RE.fullmatch(item) for item in normalized):
        raise DcapVerificationError(f"{field} measurements must be 48-byte lowercase hex")
    return normalized


@dataclass(frozen=True)
class TdxMeasurementPolicy:
    """Allowlisted TDX measurements and TCB outcomes required for hardware trust.

    The four boot/runtime measurements are mandatory.  Each field may contain multiple values to
    support a deliberate platform rotation.  Advisories fail closed unless explicitly allowlisted.
    """

    measurements: tuple[tuple[str, frozenset[str]], ...]
    accepted_tcb_statuses: frozenset[str] = frozenset({"UpToDate"})
    allowed_advisories: frozenset[str] = frozenset()

    @classmethod
    def from_dict(cls, value) -> "TdxMeasurementPolicy":
        if not isinstance(value, dict) or value.get("version") != _POLICY_VERSION:
            raise DcapVerificationError("TDX policy must be a version-1 object")
        raw_measurements = value.get("measurements")
        if not isinstance(raw_measurements, dict):
            raise DcapVerificationError("TDX policy is missing measurements")
        missing = [name for name in _MEASUREMENT_FIELDS if name not in raw_measurements]
        if missing:
            raise DcapVerificationError(
                "TDX policy is missing mandatory measurements: " + ", ".join(missing)
            )
        unknown = set(raw_measurements) - set(
            _MEASUREMENT_FIELDS + _OPTIONAL_MEASUREMENT_FIELDS
        )
        if unknown:
            raise DcapVerificationError(
                "TDX policy contains unknown measurements: " + ", ".join(sorted(unknown))
            )
        measurements = tuple(
            sorted(
                (name, _measurement_values(raw, field=name))
                for name, raw in raw_measurements.items()
            )
        )
        statuses = value.get("accepted_tcb_statuses", ["UpToDate"])
        if not isinstance(statuses, list) or not statuses or not all(
            isinstance(item, str) and item for item in statuses
        ):
            raise DcapVerificationError("accepted_tcb_statuses must be a non-empty string list")
        advisories = value.get("allowed_advisories", [])
        if not isinstance(advisories, list) or not all(
            isinstance(item, str) and item for item in advisories
        ):
            raise DcapVerificationError("allowed_advisories must be a string list")
        return cls(
            measurements=measurements,
            accepted_tcb_statuses=frozenset(statuses),
            allowed_advisories=frozenset(advisories),
        )

    @classmethod
    def from_file(cls, path) -> "TdxMeasurementPolicy":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DcapVerificationError("cannot read TDX measurement policy") from exc
        return cls.from_dict(value)

    def to_dict(self) -> dict:
        return {
            "version": _POLICY_VERSION,
            "measurements": {
                name: sorted(values) for name, values in self.measurements
            },
            "accepted_tcb_statuses": sorted(self.accepted_tcb_statuses),
            "allowed_advisories": sorted(self.allowed_advisories),
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def verify_measurements(self, report) -> bool:
        for name, allowed in self.measurements:
            raw = getattr(report, name, None)
            try:
                actual = bytes(raw).hex()
            except (TypeError, ValueError):
                return False
            if actual not in allowed:
                return False
        return True


@dataclass(frozen=True)
class IntelVerificationResult:
    """Sanitized outcome returned to the Polaris receipt verifier."""

    chain_verified: bool
    tcb_accepted: bool
    measurements_verified: bool
    backend: str
    policy_digest: str
    tcb_status: str = ""
    advisory_ids: tuple[str, ...] = ()
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.chain_verified and self.tcb_accepted and self.measurements_verified

    @classmethod
    def failed(cls, *, policy_digest: str, detail: str) -> "IntelVerificationResult":
        return cls(
            chain_verified=False,
            tcb_accepted=False,
            measurements_verified=False,
            backend="dcap-qvl-offline",
            policy_digest=policy_digest,
            detail=detail,
        )


def _decode_collateral(collateral) -> dict:
    if isinstance(collateral, dict):
        value = collateral
    elif isinstance(collateral, str):
        if len(collateral) > _MAX_COLLATERAL_BYTES * 2:
            raise DcapVerificationError("collateral exceeds the size limit")
        try:
            value = json.loads(collateral)
        except ValueError:
            try:
                raw = base64.b64decode(collateral.encode("ascii"), validate=True)
            except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
                raise DcapVerificationError("collateral is neither JSON nor base64 JSON") from exc
            if len(raw) > _MAX_COLLATERAL_BYTES:
                raise DcapVerificationError("collateral exceeds the size limit")
            try:
                value = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise DcapVerificationError("base64 collateral does not contain JSON") from exc
    else:
        raise DcapVerificationError("complete DCAP collateral is required")
    if not isinstance(value, dict):
        raise DcapVerificationError("collateral must decode to an object")
    if "dcap_qvl" in value:
        value = value["dcap_qvl"]
        if not isinstance(value, dict):
            raise DcapVerificationError("dcap_qvl collateral must be an object")
    if set(value) >= {"v", "items", "urls"}:
        raise DcapVerificationError(
            "Polaris cache bundle is incomplete for independent DCAP verification"
        )
    missing = sorted(_QVL_COLLATERAL_FIELDS - set(value))
    if missing:
        raise DcapVerificationError(
            "DCAP collateral is missing required fields: " + ", ".join(missing)
        )
    return value


class OfflineDcapQvlVerifier:
    """Verify a TDX quote locally with complete collateral and an explicit policy.

    No method in this class performs network I/O.  ``module_loader`` exists for deterministic tests;
    production uses the pinned optional ``dcap-qvl`` package.
    """

    backend = "dcap-qvl-offline"

    def __init__(
        self,
        policy: TdxMeasurementPolicy,
        *,
        now: Callable[[], float] = time.time,
        module_loader: Callable[[], object] | None = None,
    ):
        if not isinstance(policy, TdxMeasurementPolicy):
            raise DcapVerificationError("an explicit TDX measurement policy is required")
        self.policy = policy
        self._now = now
        self._module_loader = module_loader or (lambda: importlib.import_module("dcap_qvl"))
        self.last_result: IntelVerificationResult | None = None

    def __call__(self, quote: bytes, collateral) -> IntelVerificationResult:
        try:
            normalized = _decode_collateral(collateral)
            qvl = self._module_loader()
            parsed = qvl.parse_quote(quote)
            if not parsed.is_tdx() or parsed.quote_type() != "TDX":
                raise DcapVerificationError("quote is not Intel TDX")
            collateral_obj = qvl.QuoteCollateralV3.from_json(_canonical_json(normalized))
            verified = qvl.verify(quote, collateral_obj, int(self._now()))
            status = str(getattr(verified, "status", ""))
            advisories = tuple(
                sorted(str(item) for item in (getattr(verified, "advisory_ids", None) or ()))
            )
            tcb_accepted = status in self.policy.accepted_tcb_statuses and set(
                advisories
            ).issubset(self.policy.allowed_advisories)
            # dcap-qvl 0.5.3 authenticates the complete quote but its Python
            # ``VerifiedReport`` exposes only status/advisories.  Read measurements from the same
            # already-verified quote object; newer bindings may expose ``verified.report`` directly.
            verified_report = getattr(verified, "report", None) or getattr(parsed, "report", None)
            measurements_verified = self.policy.verify_measurements(verified_report)
            result = IntelVerificationResult(
                chain_verified=True,
                tcb_accepted=tcb_accepted,
                measurements_verified=measurements_verified,
                backend=self.backend,
                policy_digest=self.policy.digest,
                tcb_status=status,
                advisory_ids=advisories,
                detail=(
                    "DCAP chain, TCB policy, and TDX measurements verified"
                    if tcb_accepted and measurements_verified
                    else "DCAP cryptography passed but local TCB or measurement policy rejected"
                ),
            )
        except (
            DcapVerificationError,
            ImportError,
            AttributeError,
            TypeError,
            ValueError,
            RuntimeError,
            OSError,
        ):
            # Do not expose dependency paths, collateral contents, or native verifier errors.  The
            # operator gets a stable category while the receipt remains safe to render publicly.
            result = IntelVerificationResult.failed(
                policy_digest=self.policy.digest,
                detail="offline DCAP verification failed or collateral is incomplete",
            )
        self.last_result = result
        return result


def build_policy_from_verified_report(report, *, tcb_status: str) -> dict:
    """Build a reviewable policy draft from an already independently verified report.

    This helper does not verify a quote and must never be called on merely parsed/untrusted bytes.
    It is intentionally explicit about that trust boundary through its name and required status.
    """
    if tcb_status != "UpToDate":
        raise DcapVerificationError("policy drafts require an independently verified UpToDate TCB")
    measurements: Mapping[str, object] = {
        name: getattr(report, name, None) for name in _MEASUREMENT_FIELDS
    }
    try:
        encoded = {name: bytes(raw).hex() for name, raw in measurements.items()}
    except (TypeError, ValueError) as exc:
        raise DcapVerificationError("verified report is missing TDX measurements") from exc
    policy = TdxMeasurementPolicy.from_dict(
        {
            "version": _POLICY_VERSION,
            "measurements": encoded,
            "accepted_tcb_statuses": ["UpToDate"],
            "allowed_advisories": [],
        }
    )
    return policy.to_dict()
