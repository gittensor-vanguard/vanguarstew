"""CLI tests for scripts/verify_polaris.py — the skeptic-facing Polaris receipt verifier.

Focus: a bad ``--dcap-policy`` / ``--dcap-collateral`` path must be reported as the input that
actually failed, not always as "cannot read receipt" (#2069). ``_load`` names the input via its
``what`` argument, and the three call sites pass ``receipt`` / ``DCAP policy`` / ``DCAP collateral``.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts import verify_polaris  # noqa: E402

# Required CLI args unrelated to the load paths under test; concrete but arbitrary.
_BASE = ["--nonce", "ab" * 32, "--e2e-pubkey", "cHViaw==", "--image", "img@sha256:" + "a" * 64]


def _valid_receipt(tmp_path):
    # A minimal receipt PolarisReceipt.from_dict accepts (no tee_attestation/verification keys,
    # string binding digests default to ""), so run() gets past the receipt parse to the DCAP
    # loads.
    p = tmp_path / "receipt.json"
    p.write_text("{}", encoding="utf-8")
    return str(p)


# --- _load names the failing input --------------------------------------------------------

def test_load_defaults_to_receipt_label(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        verify_polaris._load(str(tmp_path / "missing.json"))
    assert exc.value.code == 2
    assert "cannot read receipt" in capsys.readouterr().err


@pytest.mark.parametrize("what", ["DCAP policy", "DCAP collateral"])
def test_load_reports_the_named_input(tmp_path, capsys, what):
    with pytest.raises(SystemExit) as exc:
        verify_polaris._load(str(tmp_path / "missing.json"), what)
    assert exc.value.code == 2
    assert f"cannot read {what}" in capsys.readouterr().err


# --- end-to-end through run() -------------------------------------------------------------

def test_bad_receipt_path_names_receipt(tmp_path, capsys):
    missing = str(tmp_path / "nope.json")
    with pytest.raises(SystemExit) as exc:
        verify_polaris.run(["--receipt", missing, *_BASE])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read receipt" in err
    assert "cannot read DCAP" not in err


def test_bad_dcap_policy_path_names_dcap_policy(tmp_path, capsys):
    # Regression for #2069: the policy load previously reported "cannot read receipt".
    receipt = _valid_receipt(tmp_path)
    missing = str(tmp_path / "nope.json")
    with pytest.raises(SystemExit) as exc:
        verify_polaris.run(["--receipt", receipt, *_BASE, "--dcap-policy", missing])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read DCAP policy" in err
    assert "cannot read receipt" not in err
