"""Regression tests for the verify_polaris CLI's input error handling (issue #2069).

`verify_polaris` is the skeptic-facing CLI that verifies a saved Polaris TDX receipt and its
benchmark evidence (Phase 1 of #1935). It loads three separate JSON inputs — the receipt and the
optional `--dcap-policy` / `--dcap-collateral` — through one `_load` helper. These tests pin that
each input is named correctly in the exit-2 error (a bad policy/collateral path used to be
misreported as "cannot read receipt"), and that the loader/argument guards hold. The module had no
tests before.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import scripts.verify_polaris as vp  # noqa: E402


def _run(argv, capsys):
    try:
        code = vp.run(argv)
    except SystemExit as exc:
        return ("exit", exc.code, capsys.readouterr().err)
    return ("return", code, capsys.readouterr().err)


def _receipt_file(tmp_path):
    # from_dict is lenient, so a minimal object parses and execution reaches the optional
    # policy/collateral loaders -- which is where the mislabeling used to happen.
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps({"foo": 1}), encoding="utf-8")
    return str(path)


_DUMMY = ["--nonce", "0" * 64, "--e2e-pubkey", "AAAA", "--image", "ghcr.io/o/e@sha256:" + "a" * 64]


# ---- _load names the input that failed (the fix) -------------------------------------------


def test_load_labels_each_input_kind(tmp_path, capsys):
    missing = str(tmp_path / "gone.json")
    for what in ("receipt", "DCAP policy", "DCAP collateral"):
        try:
            vp._load(missing, what)
            raise AssertionError("expected SystemExit")
        except SystemExit as exc:
            assert exc.code == 2
        assert f"cannot read {what}" in capsys.readouterr().err


def test_load_defaults_to_receipt(tmp_path, capsys):
    try:
        vp._load(str(tmp_path / "gone.json"))
    except SystemExit as exc:
        assert exc.code == 2
    assert "cannot read receipt" in capsys.readouterr().err


# ---- CLI-level: the right file is named ----------------------------------------------------


def test_bad_receipt_path_exits_2_as_receipt(tmp_path, capsys):
    kind, code, err = _run(["--receipt", str(tmp_path / "nope.json")] + _DUMMY, capsys)
    assert (kind, code) == ("exit", 2)
    assert "cannot read receipt" in err


def test_bad_dcap_policy_path_is_reported_as_policy_not_receipt(tmp_path, capsys):
    # The bug: this used to print "cannot read receipt" for a bad --dcap-policy path.
    argv = ["--receipt", _receipt_file(tmp_path)] + _DUMMY + \
        ["--dcap-policy", str(tmp_path / "no-policy.json")]
    kind, code, err = _run(argv, capsys)
    assert (kind, code) == ("exit", 2)
    assert "cannot read DCAP policy" in err
    assert "cannot read receipt" not in err


# ---- CLI-level: argument-interplay guard ---------------------------------------------------


def test_dcap_collateral_without_policy_is_rejected(tmp_path, capsys):
    argv = ["--receipt", _receipt_file(tmp_path)] + _DUMMY + \
        ["--dcap-collateral", str(tmp_path / "collateral.json")]
    kind, code, err = _run(argv, capsys)
    assert (kind, code) == ("return", 2)
    assert "--dcap-collateral requires --dcap-policy" in err
