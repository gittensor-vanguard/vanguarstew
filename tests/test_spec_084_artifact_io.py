"""Characterization tests for Spec 084 — the shared artifact-loader CLI error contract.

These pin the observable behaviour of :func:`scripts.artifact_io.load_artifact` — the single
source of the path-error taxonomy every artifact-consuming gate CLI relies on — so the Spec 084
acceptance criteria have executable teeth. Every asserted exit code and message prefix was taken
from the live loader, not hand-written.

The contract's whole point is "a distinct, actionable message + a consistent exit 2 over a raw
traceback" (issues #612 / #604 / #641 / #608 / #554 / #1906 / #1958), so each failure class is
exercised against a real filesystem fixture.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.artifact_io import load_artifact  # noqa: E402


def _expect_exit(path, capsys):
    """Run load_artifact(path), assert it exits 2, and return the stripped stderr text."""
    with pytest.raises(SystemExit) as excinfo:
        load_artifact(path)
    assert excinfo.value.code == 2
    return capsys.readouterr().err.strip()


# ---- success -------------------------------------------------------------------------------


def test_loads_a_json_object_and_returns_it(tmp_path):
    p = tmp_path / "good.json"
    p.write_text(json.dumps({"composite_mean": 0.5, "tasks": 3}), encoding="utf-8")
    assert load_artifact(str(p)) == {"composite_mean": 0.5, "tasks": 3}


# ---- path-error taxonomy (each a distinct message, all exit 2) -----------------------------


def test_missing_file(tmp_path, capsys):
    err = _expect_exit(str(tmp_path / "nope.json"), capsys)
    assert err.startswith("artifact not found:")


def test_broken_symlink_is_distinguished_from_a_missing_file(tmp_path, capsys):
    link = tmp_path / "broken"
    os.symlink(str(tmp_path / "does-not-exist"), str(link))
    err = _expect_exit(str(link), capsys)
    assert err.startswith("artifact is a broken symlink (target does not exist):")


def test_directory_path(tmp_path, capsys):
    err = _expect_exit(str(tmp_path), capsys)
    # On Windows a directory surfaces as PermissionError; on POSIX as IsADirectoryError.
    assert err.startswith("artifact path is a directory, not a file:") or \
        err.startswith("artifact is not readable")


def test_parent_component_is_not_a_directory(tmp_path, capsys):
    afile = tmp_path / "good.json"
    afile.write_text("{}", encoding="utf-8")
    err = _expect_exit(str(afile / "child.json"), capsys)
    assert err.startswith("artifact path is not a file (a parent component is not a directory):")


def test_symlink_loop_is_not_reported_as_not_found(tmp_path, capsys):
    a = tmp_path / "loopa"
    b = tmp_path / "loopb"
    os.symlink(str(b), str(a))
    os.symlink(str(a), str(b))
    err = _expect_exit(str(a), capsys)
    assert err.startswith("artifact path is a symlink loop:")


def test_invalid_json(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    err = _expect_exit(str(p), capsys)
    assert err.startswith("artifact is not valid JSON (")


def test_non_utf8_is_distinguished_from_invalid_json(tmp_path, capsys):
    # UnicodeDecodeError subclasses ValueError, so it must be reported before the JSON arm.
    p = tmp_path / "nu.json"
    p.write_bytes(b'\xff\xfe{"a":1}')
    err = _expect_exit(str(p), capsys)
    assert err.startswith("artifact is not valid UTF-8 JSON (")


def test_non_object_root_is_rejected(tmp_path, capsys):
    # A syntactically valid JSON array/scalar is not an artifact; the consumers index by key.
    p = tmp_path / "arr.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    err = _expect_exit(str(p), capsys)
    assert err.startswith("artifact must be a JSON object:")


def test_oversized_int_literal_is_a_clean_json_error_not_a_traceback(tmp_path, capsys):
    # json.load raises a plain ValueError (not JSONDecodeError) on an int literal beyond the
    # py3.11+ int-string-conversion limit; it must still be caught as a clean JSON error.
    p = tmp_path / "big.json"
    p.write_text("{\"n\": " + "9" * 5000 + "}", encoding="utf-8")
    err = _expect_exit(str(p), capsys)
    assert err.startswith("artifact is not valid JSON (")


# ---- exit-code contract --------------------------------------------------------------------


def test_every_failure_class_uses_exit_2_never_1(tmp_path, capsys):
    # Exit 2 is reserved for load failures so it never collides with the gating exit 1 that
    # --strict / --fail-on-regression use on the consumer CLIs. One representative per branch.
    missing = str(tmp_path / "gone.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    arr = tmp_path / "arr.json"
    arr.write_text("42", encoding="utf-8")
    for path in (missing, str(bad), str(arr), str(tmp_path)):
        with pytest.raises(SystemExit) as excinfo:
            load_artifact(path)
        assert excinfo.value.code == 2
        capsys.readouterr()  # drain
