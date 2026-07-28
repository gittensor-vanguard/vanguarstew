"""Offline policy and adapter tests for independent Intel TDX verification."""

import base64
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.intel_dcap import (  # noqa: E402
    DcapVerificationError,
    OfflineDcapQvlVerifier,
    TdxMeasurementPolicy,
    build_policy_from_verified_report,
)

MEASUREMENTS = {
    "mr_td": "11" * 48,
    "rt_mr0": "22" * 48,
    "rt_mr1": "33" * 48,
    "rt_mr2": "44" * 48,
}


def _policy(**overrides):
    value = {
        "version": 1,
        "measurements": MEASUREMENTS,
        "accepted_tcb_statuses": ["UpToDate"],
        "allowed_advisories": [],
    }
    value.update(overrides)
    return TdxMeasurementPolicy.from_dict(value)


def _complete_collateral():
    return {
        "pck_crl_issuer_chain": "issuer",
        "root_ca_crl": [1, 2],
        "pck_crl": [3, 4],
        "tcb_info_issuer_chain": "tcb-issuer",
        "tcb_info": "{}",
        "tcb_info_signature": [5, 6],
        "qe_identity_issuer_chain": "qe-issuer",
        "qe_identity": "{}",
        "qe_identity_signature": [7, 8],
    }


class _FakeCollateral:
    value = None

    @classmethod
    def from_json(cls, value):
        cls.value = json.loads(value)
        return cls.value


class _FakeParsedQuote:
    def __init__(self):
        self.report = SimpleNamespace(
            **{name: bytes.fromhex(value) for name, value in MEASUREMENTS.items()}
        )

    def is_tdx(self):
        return True

    def quote_type(self):
        return "TDX"


class _FakeQvl:
    QuoteCollateralV3 = _FakeCollateral
    status = "UpToDate"
    advisories = ()
    verify_error = None
    seen = None

    @staticmethod
    def parse_quote(quote):
        assert quote == b"tdx-quote"
        return _FakeParsedQuote()

    @classmethod
    def verify(cls, quote, collateral, now):
        cls.seen = (quote, collateral, now)
        if cls.verify_error:
            raise cls.verify_error
        # Match dcap-qvl 0.5.3: the verified result carries status/advisories while measurements
        # remain on the parsed quote object authenticated by this successful call.
        return SimpleNamespace(status=cls.status, advisory_ids=cls.advisories)


@pytest.fixture(autouse=True)
def _reset_fake_qvl():
    _FakeQvl.status = "UpToDate"
    _FakeQvl.advisories = ()
    _FakeQvl.verify_error = None
    _FakeQvl.seen = None
    _FakeCollateral.value = None


def test_policy_requires_all_boot_measurements_and_has_stable_digest():
    first = _policy()
    reordered = _policy(measurements=dict(reversed(list(MEASUREMENTS.items()))))
    assert first.digest == reordered.digest
    assert len(first.digest) == 64

    missing = dict(MEASUREMENTS)
    missing.pop("rt_mr2")
    with pytest.raises(DcapVerificationError, match="rt_mr2"):
        _policy(measurements=missing)
    with pytest.raises(DcapVerificationError, match="48-byte"):
        _policy(measurements={**MEASUREMENTS, "mr_td": "short"})


def test_complete_collateral_quote_tcb_and_measurements_verify_offline():
    verifier = OfflineDcapQvlVerifier(
        _policy(), now=lambda: 1_700_000_000, module_loader=lambda: _FakeQvl
    )
    result = verifier(b"tdx-quote", _complete_collateral())
    assert result.ok is True
    assert result.chain_verified is True
    assert result.tcb_accepted is True
    assert result.measurements_verified is True
    assert result.tcb_status == "UpToDate"
    assert result.policy_digest == _policy().digest
    assert _FakeQvl.seen == (b"tdx-quote", _complete_collateral(), 1_700_000_000)


def test_measurement_tcb_and_advisory_policy_fail_closed():
    bad_measurements = dict(MEASUREMENTS)
    bad_measurements["mr_td"] = "aa" * 48
    measurement_result = OfflineDcapQvlVerifier(
        _policy(measurements=bad_measurements), module_loader=lambda: _FakeQvl
    )(b"tdx-quote", _complete_collateral())
    assert measurement_result.chain_verified is True
    assert measurement_result.measurements_verified is False
    assert measurement_result.ok is False

    _FakeQvl.status = "OutOfDate"
    tcb_result = OfflineDcapQvlVerifier(_policy(), module_loader=lambda: _FakeQvl)(
        b"tdx-quote", _complete_collateral()
    )
    assert tcb_result.chain_verified is True
    assert tcb_result.tcb_accepted is False

    _FakeQvl.status = "UpToDate"
    _FakeQvl.advisories = ("INTEL-SA-TEST",)
    advisory_result = OfflineDcapQvlVerifier(_policy(), module_loader=lambda: _FakeQvl)(
        b"tdx-quote", _complete_collateral()
    )
    assert advisory_result.tcb_accepted is False


def test_polaris_cache_bundle_is_identified_as_incomplete_without_loading_qvl():
    loaded = False

    def loader():
        nonlocal loaded
        loaded = True
        return _FakeQvl

    cache = base64.b64encode(
        json.dumps({"v": 1, "items": {"url": "body"}, "urls": ["url"]}).encode()
    ).decode()
    result = OfflineDcapQvlVerifier(_policy(), module_loader=loader)(b"tdx-quote", cache)
    assert result.ok is False
    assert result.detail == "offline DCAP verification failed or collateral is incomplete"
    assert loaded is False


def test_missing_dependency_and_native_verification_error_are_sanitized():
    def missing():
        raise ImportError("private installation path")

    missing_result = OfflineDcapQvlVerifier(_policy(), module_loader=missing)(
        b"tdx-quote", _complete_collateral()
    )
    assert missing_result.ok is False
    assert "path" not in missing_result.detail

    _FakeQvl.verify_error = ValueError("certificate internals")
    native_result = OfflineDcapQvlVerifier(_policy(), module_loader=lambda: _FakeQvl)(
        b"tdx-quote", _complete_collateral()
    )
    assert native_result.ok is False
    assert "certificate" not in native_result.detail


def test_policy_draft_requires_a_preverified_uptodate_report():
    report = SimpleNamespace(
        **{name: bytes.fromhex(value) for name, value in MEASUREMENTS.items()}
    )
    draft = build_policy_from_verified_report(report, tcb_status="UpToDate")
    assert draft["measurements"] == {name: [value] for name, value in MEASUREMENTS.items()}
    with pytest.raises(DcapVerificationError, match="UpToDate"):
        build_policy_from_verified_report(report, tcb_status="OutOfDate")
