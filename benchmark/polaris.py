"""Polaris TDX receipt verification for deterministic benchmark replays.

Polaris owns the outer hardware-attestation statement.  The interoperability contract used here is
the public client at ``cathedralai/cathedral@990c7a4:scaffold/polaris.py`` and the current service
contract at ``https://polaris.computer/docs``.  Its quote binds a fresh caller challenge, the exact
container output, and (in binding version 2) mounted-input and recorded-egress digests::

    report_data[0:32]  = sha256(nonce_hex + e2e_pubkey_b64)
    report_data[32:64] = sha256(image_digest + sha256hex(stdout)
                                + egress_log_sha256 + files_sha256)

Vanguarstew owns the inner benchmark statement.  The canonical ``stdout`` envelope carries the
existing artifact/evidence pair, whose digest chain is checked by :mod:`benchmark.attestation`.
Keeping these layers separate avoids pretending that vanguarstew's 32-byte evidence digest can be
written directly into Polaris's provider-defined 64-byte ``report_data`` layout.

This module intentionally does not copy Cathedral's validator, billing, or lane machinery.  It is
a small protocol adapter with a fail-closed verifier.  It also distinguishes a receipt Polaris says
it verified from one independently re-verified against Intel collateral: without a local verifier,
the strongest honest result is ``polaris-verified``.

The stdout envelope may contain a complete benchmark artifact.  Publish it only for public replay
inputs.  A later private-held-out phase must emit a separately designed aggregate-only envelope;
this module does not sanitize arbitrary artifacts after the fact.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

from benchmark.attestation import verify_evidence
from benchmark.intel_dcap import IntelVerificationResult
from benchmark.transcript import canonical_json

POLARIS_ENVELOPE_VERSION = 1
POLARIS_INPUT_PACKAGE_VERSION = 1
POLARIS_MAX_MOUNTED_FILES = 8
POLARIS_MAX_MOUNTED_FILE_BYTES = 256 * 1024
TDX_REPORT_DATA_OFFSET = 568
TDX_REPORT_DATA_SIZE = 64
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_CONTENT_DIGEST_RE = re.compile(r"(?:^|@)sha256:([0-9a-fA-F]{64})$")
_NONCE_RE = re.compile(r"[0-9a-fA-F]{64}")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")

IntelVerifier = Callable[[bytes, dict | str | None], IntelVerificationResult | bool]


class PolarisError(RuntimeError):
    """A malformed request, transport failure, or invalid Polaris response."""


def _content_digest(value: str) -> str:
    """Return the normalized 64-hex content digest from an image reference, or ``""``.

    Both ``sha256:<hex>`` (the resolved form returned by Polaris) and
    ``registry/name@sha256:<hex>`` (the pinned request form) are accepted.  Mutable tags are not.
    """
    match = _CONTENT_DIGEST_RE.search(value or "")
    return match.group(1).lower() if match else ""


def _decode_quote(quote_b64: str) -> bytes:
    try:
        return base64.b64decode((quote_b64 or "").encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise PolarisError("quote_b64 is not valid base64") from exc


def expected_report_data(
    nonce_hex: str,
    e2e_pubkey_b64: str,
    image_digest: str,
    stdout: str,
    *,
    egress_log_sha256: str = "",
    files_sha256: str = "",
) -> bytes:
    """Compute the v1/v2 64-byte binding used by Polaris's attestation contract.

    Empty extra digests reproduce version 1 exactly.  Version 2 supplies one or both lowercase
    hex digests and appends them in the provider-defined order before hashing the high half.
    """
    if not _NONCE_RE.fullmatch(nonce_hex or ""):
        raise PolarisError("nonce must be exactly 32 bytes encoded as 64 hex characters")
    if not isinstance(e2e_pubkey_b64, str) or not e2e_pubkey_b64:
        raise PolarisError("e2e_pubkey_b64 must be non-empty")
    if len(e2e_pubkey_b64) > 128:
        raise PolarisError("e2e_pubkey_b64 exceeds the Polaris size limit")
    try:
        base64.b64decode(e2e_pubkey_b64.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise PolarisError("e2e_pubkey_b64 is not valid base64") from exc
    if not _content_digest(image_digest):
        raise PolarisError("image_digest must be a sha256 content digest")
    if not isinstance(stdout, str):
        raise PolarisError("stdout must be a string")
    for label, value in (
        ("egress_log_sha256", egress_log_sha256),
        ("files_sha256", files_sha256),
    ):
        if not isinstance(value, str) or (value and not _SHA256_RE.fullmatch(value)):
            raise PolarisError(f"{label} must be empty or a lowercase sha256 digest")

    caller = hashlib.sha256((nonce_hex + e2e_pubkey_b64).encode("utf-8")).digest()
    stdout_hex = hashlib.sha256(stdout.encode("utf-8")).hexdigest()
    result = hashlib.sha256(
        (image_digest + stdout_hex + egress_log_sha256 + files_sha256).encode("utf-8")
    ).digest()
    return caller + result


def _encode_mounted_files(files) -> dict[str, str]:
    """Validate public input mounts and return their strict base64 request representation."""
    if files is None:
        return {}
    if not isinstance(files, dict):
        raise PolarisError("Polaris files must be a target-to-bytes mapping")
    if len(files) > POLARIS_MAX_MOUNTED_FILES:
        raise PolarisError(f"Polaris accepts at most {POLARIS_MAX_MOUNTED_FILES} mounted files")

    encoded = {}
    for target, content in files.items():
        if not isinstance(target, str):
            raise PolarisError("Polaris file targets must be strings")
        path = PurePosixPath(target)
        if (
            not target.startswith("/submission/")
            or str(path) != target
            or ".." in path.parts
            or "\x00" in target
        ):
            raise PolarisError("Polaris file targets must be normalized under /submission")
        if not isinstance(content, bytes):
            raise PolarisError("Polaris mounted file content must be bytes")
        if len(content) > POLARIS_MAX_MOUNTED_FILE_BYTES:
            raise PolarisError(
                f"Polaris mounted files must not exceed {POLARIS_MAX_MOUNTED_FILE_BYTES} bytes"
            )
        encoded[target] = base64.b64encode(content).decode("ascii")
    return encoded


def mounted_files_sha256(files: dict[str, bytes] | None) -> str:
    """Return Polaris's binding-v2 digest for a validated mounted-file mapping.

    The provider hashes UTF-8 rows sorted by target.  Each row is
    ``target + TAB + sha256(content) + newline``.  The protocol uses an empty string rather than
    the hash of an empty manifest when no files are mounted.
    """
    _encode_mounted_files(files)
    if not files:
        return ""
    manifest = "".join(
        f"{target}\t{hashlib.sha256(files[target]).hexdigest()}\n" for target in sorted(files)
    )
    return hashlib.sha256(manifest.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PolarisReceipt:
    """The protocol fields needed to verify one Polaris response.

    ``stdout`` is protocol evidence, not automatically safe to publish; see the module warning.
    ``intel_verified`` is Polaris's server-side result unless a caller separately supplies a local
    Intel verifier to :func:`verify_receipt`.
    """

    quote_b64: str
    intel_verified: bool
    image_digest: str
    stdout: str
    cost_usd: float | None = None
    stub: bool = False
    collateral: dict | str | None = None
    binding_version: int = 1
    files_sha256: str = ""
    egress_log_sha256: str = ""

    @classmethod
    def from_response(cls, response) -> "PolarisReceipt":
        if not isinstance(response, dict):
            raise PolarisError("Polaris response is not an object")
        tee = response.get("tee_attestation")
        verification = response.get("verification")
        if not isinstance(tee, dict) or not isinstance(verification, dict):
            raise PolarisError("Polaris response is missing attestation or verification data")
        quote_b64 = tee.get("quote_b64")
        image_digest = response.get("image_digest") or tee.get("bound_digest")
        stdout = response.get("stdout")
        if not isinstance(quote_b64, str) or not isinstance(image_digest, str):
            raise PolarisError("Polaris response has malformed quote or image digest")
        if not isinstance(stdout, str):
            raise PolarisError("Polaris response has malformed stdout")
        raw_cost = response.get("cost_usd")
        cost = None
        if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool):
            cost = float(raw_cost)
        collateral = tee.get("collateral_b64", tee.get("collateral", response.get("collateral")))
        if not isinstance(collateral, (dict, str)):
            collateral = None
        raw_version = tee.get("binding_version", response.get("binding_version", 1))
        binding_version = (
            raw_version if isinstance(raw_version, int) and not isinstance(raw_version, bool) else 0
        )
        files_sha256 = response.get("files_sha256", tee.get("files_sha256", ""))
        egress_log_sha256 = response.get(
            "egress_log_sha256", tee.get("egress_log_sha256", "")
        )
        if not isinstance(files_sha256, str) or not isinstance(egress_log_sha256, str):
            raise PolarisError("Polaris response has malformed binding digests")
        return cls(
            quote_b64=quote_b64,
            intel_verified=verification.get("intel_verified") is True,
            image_digest=image_digest,
            stdout=stdout,
            cost_usd=cost,
            stub=response.get("stub") is True,
            collateral=collateral,
            binding_version=binding_version,
            files_sha256=files_sha256,
            egress_log_sha256=egress_log_sha256,
        )

    @classmethod
    def from_dict(cls, value) -> "PolarisReceipt":
        if not isinstance(value, dict):
            raise PolarisError("receipt is not an object")
        if "tee_attestation" in value or "verification" in value:
            return cls.from_response(value)
        files_sha256 = value.get("files_sha256", "")
        egress_log_sha256 = value.get("egress_log_sha256", "")
        if not isinstance(files_sha256, str) or not isinstance(egress_log_sha256, str):
            raise PolarisError("receipt has malformed binding digests")
        return cls(
            quote_b64=value.get("quote_b64") if isinstance(value.get("quote_b64"), str) else "",
            intel_verified=value.get("intel_verified") is True,
            image_digest=(
                value.get("image_digest") if isinstance(value.get("image_digest"), str) else ""
            ),
            stdout=value.get("stdout") if isinstance(value.get("stdout"), str) else "",
            cost_usd=(
                float(value["cost_usd"])
                if isinstance(value.get("cost_usd"), (int, float))
                and not isinstance(value.get("cost_usd"), bool)
                else None
            ),
            stub=value.get("stub") is True,
            collateral=(
                value.get("collateral")
                if isinstance(value.get("collateral"), (dict, str))
                else None
            ),
            binding_version=(
                value.get("binding_version", 1)
                if isinstance(value.get("binding_version", 1), int)
                and not isinstance(value.get("binding_version", 1), bool)
                else 0
            ),
            files_sha256=files_sha256,
            egress_log_sha256=egress_log_sha256,
        )

    def to_dict(self) -> dict:
        value = {
            "quote_b64": self.quote_b64,
            "intel_verified": self.intel_verified,
            "image_digest": self.image_digest,
            "stdout": self.stdout,
            "stub": self.stub,
            "binding_version": self.binding_version,
            "files_sha256": self.files_sha256,
            "egress_log_sha256": self.egress_log_sha256,
        }
        if self.cost_usd is not None:
            value["cost_usd"] = self.cost_usd
        if self.collateral is not None:
            value["collateral"] = self.collateral
        return value


class PolarisClient:
    """Minimal live client for Polaris's attested-execution endpoint.

    There is no implicit offline stub and no default service URL.  Calling this class is therefore
    an explicit network/spend action by the orchestrator that supplied ``base_url`` and ``api_key``.
    """

    def __init__(self, *, base_url: str, api_key: str, timeout: float = 240.0, opener=None):
        if not isinstance(base_url, str) or not base_url.startswith("https://"):
            raise PolarisError("Polaris base_url must use https")
        if not isinstance(api_key, str) or not api_key:
            raise PolarisError("Polaris api_key must be non-empty")
        if timeout <= 0:
            raise PolarisError("Polaris timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = float(timeout)
        self._opener = opener or urllib.request.urlopen

    @classmethod
    def from_env_file(
        cls,
        path,
        *,
        base_url: str = "",
        api_key_name: str = "POLARIS_API_KEY",
        base_url_name: str = "POLARIS_URL",
        timeout: float = 240.0,
        opener=None,
    ) -> "PolarisClient":
        """Build a client from a permission-restricted dotenv file without sourcing it.

        Only simple ``NAME=value`` rows are parsed.  The file is never loaded into ``os.environ``,
        and secret values are never included in errors.  ``api_key_name`` exists for local secret
        stores with a nonstandard variable name; committed integrations should use the default.
        """
        env_path = Path(path)
        try:
            file_mode = env_path.stat().st_mode
            text = env_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolarisError("cannot read Polaris env file") from exc
        if os.name != "nt" and file_mode & 0o077:
            raise PolarisError("Polaris env file must not be accessible by group or others")

        values = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.removeprefix("export ").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue
            if key in values:
                raise PolarisError("Polaris env file contains a duplicate variable")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
        api_key = values.get(api_key_name, "")
        if not api_key and api_key_name == "POLARIS_API_KEY":
            api_key = values.get("POLARIS_KEY", "")  # compatibility with the older scaffold
        return cls(
            base_url=base_url or values.get(base_url_name, ""),
            api_key=api_key,
            timeout=timeout,
            opener=opener,
        )

    def _request_json(self, request) -> dict:
        try:
            with self._opener(request, timeout=self.timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (OSError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            # Never include response bodies or request headers: either can contain credentials or
            # private workload details.  The exception class is enough for an operator diagnostic.
            raise PolarisError(f"Polaris request failed ({type(exc).__name__})") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise PolarisError("Polaris response exceeded the size limit")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise PolarisError("Polaris returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PolarisError("Polaris response is not an object")
        return payload

    def check_key(self, account_url: str = "https://api.polaris.computer") -> bool:
        """Check the live account API without starting a TDX run or reading key metadata."""
        if not isinstance(account_url, str) or not account_url.startswith("https://"):
            raise PolarisError("Polaris account_url must use https")
        request = urllib.request.Request(
            account_url.rstrip("/") + "/api/keys",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "User-Agent": "vanguarstew-polaris/1",
            },
        )
        try:
            with self._opener(request, timeout=self.timeout):
                return True
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                return False
            raise PolarisError(f"Polaris key check failed (HTTP {exc.code})") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise PolarisError(f"Polaris key check failed ({type(exc).__name__})") from exc

    def attest(
        self,
        *,
        nonce: str,
        e2e_pubkey_b64: str,
        image: str,
        workload: str,
        egress: str = "none",
        files: dict[str, bytes] | None = None,
    ) -> PolarisReceipt:
        """Run a digest-pinned image and return the complete receipt needed for verification."""
        if not _content_digest(image):
            raise PolarisError("Polaris image must be pinned by sha256 content digest")
        # Validate the caller-controlled pieces before a potentially billable request.  The dummy
        # digest/stdout are used only for validation; the real result binding arrives in the quote.
        expected_report_data(nonce, e2e_pubkey_b64, image, "")
        if not isinstance(workload, str) or not workload:
            raise PolarisError("Polaris workload must be non-empty")
        if len(workload.encode("utf-8")) > 16 * 1024:
            raise PolarisError("Polaris workload exceeds the size limit")
        if egress != "none":
            raise PolarisError("vanguarstew Polaris runs currently require egress='none'")
        encoded_files = _encode_mounted_files(files)

        request_body = {
            "nonce": nonce,
            "e2e_pubkey_b64": e2e_pubkey_b64,
            "image": image,
            "workload": workload,
            "egress": egress,
        }
        if encoded_files:
            request_body["files"] = encoded_files
        body = json.dumps(request_body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + "/v1/attest",
            method="POST",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "vanguarstew-polaris/1",
            },
        )
        return PolarisReceipt.from_response(self._request_json(request))


def verify_receipt(
    receipt,
    *,
    nonce: str,
    e2e_pubkey_b64: str,
    expected_image: str,
    expected_files_sha256: str | None = None,
    expected_egress_log_sha256: str = "",
    require_live: bool = True,
    intel_verifier: IntelVerifier | None = None,
) -> dict:
    """Verify the complete Polaris binding and optionally the Intel chain locally.

    ``ok`` means every requested check passed.  With no ``intel_verifier``, a successful live
    result is labeled ``polaris-verified`` rather than independently verified.
    """
    try:
        parsed = (
            receipt if isinstance(receipt, PolarisReceipt) else PolarisReceipt.from_dict(receipt)
        )
        quote = _decode_quote(parsed.quote_b64)
        expected = expected_report_data(
            nonce,
            e2e_pubkey_b64,
            parsed.image_digest,
            parsed.stdout,
            egress_log_sha256=parsed.egress_log_sha256,
            files_sha256=parsed.files_sha256,
        )
    except PolarisError as exc:
        return {
            "ok": False,
            "checks": {"receipt_shape": False},
            "verification_level": "unverified",
            "hardware_attested": False,
            "hardware_attestation_claimed": False,
            "independent_intel_verified": None,
            "detail": str(exc),
        }

    report_data = quote[TDX_REPORT_DATA_OFFSET : TDX_REPORT_DATA_OFFSET + TDX_REPORT_DATA_SIZE]
    expected_hex = _content_digest(expected_image)
    resolved_hex = _content_digest(parsed.image_digest)
    has_v2_extras = bool(parsed.files_sha256 or parsed.egress_log_sha256)
    expected_version = 2 if has_v2_extras else 1
    expected_files_valid = expected_files_sha256 is None or (
        isinstance(expected_files_sha256, str)
        and bool(_SHA256_RE.fullmatch(expected_files_sha256))
    )
    expected_egress_valid = isinstance(expected_egress_log_sha256, str) and (
        not expected_egress_log_sha256
        or bool(_SHA256_RE.fullmatch(expected_egress_log_sha256))
    )
    checks = {
        "receipt_shape": True,
        "live_receipt": not parsed.stub if require_live else True,
        "quote_structure": len(quote) >= TDX_REPORT_DATA_OFFSET + TDX_REPORT_DATA_SIZE,
        "caller_binding": len(report_data) == TDX_REPORT_DATA_SIZE
        and hmac.compare_digest(report_data[:32], expected[:32]),
        "result_binding": len(report_data) == TDX_REPORT_DATA_SIZE
        and hmac.compare_digest(report_data[32:], expected[32:]),
        "expected_image_pinned": bool(expected_hex),
        "resolved_image_pinned": bool(resolved_hex),
        "image_digest": bool(expected_hex) and expected_hex == resolved_hex,
        "polaris_intel_verified": parsed.intel_verified,
        "binding_version": parsed.binding_version == expected_version,
        # A v2 quote proves the provider bound *a* files digest.  To prove it is the digest the
        # verifier expected, callers must provide that independently obtained value.  Omitting it
        # fails closed whenever a receipt claims mounted files.
        "expected_files_digest": expected_files_valid
        and (
            (not parsed.files_sha256 and expected_files_sha256 in {None, ""})
            or (
                bool(parsed.files_sha256)
                and bool(expected_files_sha256)
                and hmac.compare_digest(parsed.files_sha256, expected_files_sha256)
            )
        ),
        "expected_egress_digest": expected_egress_valid
        and hmac.compare_digest(parsed.egress_log_sha256, expected_egress_log_sha256),
    }
    polaris_verified = all(checks.values())

    independent = None
    independent_result = None
    if intel_verifier is not None:
        if checks["quote_structure"]:
            try:
                raw_result = intel_verifier(quote, parsed.collateral)
                if isinstance(raw_result, IntelVerificationResult):
                    independent_result = raw_result
                    independent = raw_result.chain_verified
                    checks["intel_chain_local"] = raw_result.chain_verified
                    checks["intel_tcb_policy"] = raw_result.tcb_accepted
                    checks["tdx_measurement_policy"] = raw_result.measurements_verified
                else:
                    # A legacy boolean callback can prove only that an opaque check returned true.
                    # It cannot assert which TCB status or measurements were accepted, so it never
                    # upgrades the receipt to independently hardware-attested.
                    independent = bool(raw_result)
                    checks["intel_chain_local"] = independent
                    checks["intel_tcb_policy"] = False
                    checks["tdx_measurement_policy"] = False
            except Exception:
                independent = False
                checks["intel_chain_local"] = False
                checks["intel_tcb_policy"] = False
                checks["tdx_measurement_policy"] = False
        else:
            independent = False
            checks["intel_chain_local"] = False
            checks["intel_tcb_policy"] = False
            checks["tdx_measurement_policy"] = False

    ok = all(checks.values())
    if parsed.stub:
        level = "stub" if ok else "unverified"
    elif ok and independent is True:
        level = "independently-verified"
    elif ok:
        level = "polaris-verified"
    else:
        level = "unverified"
    detail = (
        "all requested checks passed"
        if ok
        else "; ".join(f"{name} FAILED" for name, passed in checks.items() if not passed)
    )
    result = {
        "ok": ok,
        "checks": checks,
        "verification_level": level,
        # The server result is a claim we can label and consume, but ``hardware_attested`` stays
        # false until the caller supplies an independent Intel verifier.  This prevents downstream
        # code from silently collapsing "Polaris says it verified" into "we verified locally".
        "hardware_attested": ok and not parsed.stub and independent is True,
        "hardware_attestation_claimed": polaris_verified and not parsed.stub,
        "independent_intel_verified": independent,
        "report_data": report_data.hex() if len(report_data) == TDX_REPORT_DATA_SIZE else "",
        "files_sha256": parsed.files_sha256,
        "egress_log_sha256": parsed.egress_log_sha256,
        "detail": detail,
    }
    if independent_result is not None:
        result["independent_verification"] = {
            "backend": independent_result.backend,
            "policy_digest": independent_result.policy_digest,
            "tcb_status": independent_result.tcb_status,
            "advisory_ids": list(independent_result.advisory_ids),
            "detail": independent_result.detail,
        }
    return result


def build_stdout_envelope(artifact, evidence) -> str:
    """Return the exact canonical stdout that a deterministic Polaris workload should emit."""
    return canonical_json(
        {
            "version": POLARIS_ENVELOPE_VERSION,
            "artifact": artifact,
            "evidence": evidence,
        }
    )


def verify_attested_envelope(
    receipt,
    *,
    nonce: str,
    e2e_pubkey_b64: str,
    expected_image: str,
    expected_files_sha256: str | None = None,
    expected_egress_log_sha256: str = "",
    require_live: bool = True,
    intel_verifier: IntelVerifier | None = None,
) -> dict:
    """Verify the outer Polaris quote and inner vanguarstew evidence as one proof chain."""
    try:
        parsed = (
            receipt if isinstance(receipt, PolarisReceipt) else PolarisReceipt.from_dict(receipt)
        )
    except PolarisError as exc:
        return {
            "ok": False,
            "outer": verify_receipt(
                receipt,
                nonce=nonce,
                e2e_pubkey_b64=e2e_pubkey_b64,
                expected_image=expected_image,
                expected_files_sha256=expected_files_sha256,
                expected_egress_log_sha256=expected_egress_log_sha256,
                require_live=require_live,
                intel_verifier=intel_verifier,
            ),
            "checks": {"envelope_shape": False},
            "detail": str(exc),
        }

    outer = verify_receipt(
        parsed,
        nonce=nonce,
        e2e_pubkey_b64=e2e_pubkey_b64,
        expected_image=expected_image,
        expected_files_sha256=expected_files_sha256,
        expected_egress_log_sha256=expected_egress_log_sha256,
        require_live=require_live,
        intel_verifier=intel_verifier,
    )
    try:
        envelope = json.loads(parsed.stdout)
    except ValueError:
        envelope = None
    shape_ok = isinstance(envelope, dict)
    version_ok = shape_ok and envelope.get("version") == POLARIS_ENVELOPE_VERSION
    canonical_ok = shape_ok and canonical_json(envelope) == parsed.stdout
    artifact = envelope.get("artifact") if shape_ok else None
    evidence = envelope.get("evidence") if shape_ok else None
    inner = (
        verify_evidence(artifact, evidence)
        if shape_ok
        else {"ok": False, "checks": {"evidence_shape": False}, "detail": "missing envelope"}
    )
    inputs = evidence.get("inputs") if isinstance(evidence, dict) else None
    bound_image = inputs.get("eval_image") if isinstance(inputs, dict) else ""
    image_ok = bool(_content_digest(bound_image)) and (
        _content_digest(bound_image)
        == _content_digest(parsed.image_digest)
        == _content_digest(expected_image)
    )
    checks = {
        "envelope_shape": shape_ok,
        "envelope_version": version_ok,
        "canonical_stdout": canonical_ok,
        "inner_evidence": inner.get("ok") is True,
        "inner_image_binding": image_ok,
    }
    ok = outer.get("ok") is True and all(checks.values())
    failures = [] if outer.get("ok") else [outer.get("detail", "outer receipt failed")]
    failures += [f"{name} FAILED" for name, passed in checks.items() if not passed]
    detail = "all proof-chain checks passed" if ok else "; ".join(failures)
    return {"ok": ok, "outer": outer, "inner": inner, "checks": checks, "detail": detail}
