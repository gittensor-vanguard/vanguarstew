"""Tests for the Polaris benchmark-seal planner's private-input loader (Phase 1 of #1935).

`scripts/plan_polaris_benchmark.py` reconstructs a network-free Polaris TDX seal request from
private, mode-0600 inputs (the combined report + the four raw artifacts). `load_private_json` is
the security-critical gate on those reads: it opens with `O_NOFOLLOW`, rejects broad permissions,
bounds the size, reads exactly `st_size` bytes (rejecting a concurrent grow), and requires a JSON
object. These tests pin that taxonomy, and that `main()` fails closed with a generic message that
never leaks a private path or the specific failure.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.plan_polaris_benchmark import (  # noqa: E402
    load_private_json,
    load_private_report,
    main,
)


def _private(tmp_path, name, text, mode=0o600):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)
    return str(path)


# ---- accepted input ------------------------------------------------------------------------


def test_loads_a_bounded_mode_0600_json_object(tmp_path):
    path = _private(tmp_path, "report.json", json.dumps({"a": 1, "b": [2, 3]}))
    assert load_private_json(path, max_bytes=1024, label="report") == {"a": 1, "b": [2, 3]}


def test_load_private_report_wrapper_reads_an_object(tmp_path):
    path = _private(tmp_path, "report.json", json.dumps({"combined": True}))
    assert load_private_report(path) == {"combined": True}


# ---- rejected inputs (the security taxonomy) -----------------------------------------------


def test_broad_permissions_are_rejected(tmp_path):
    # A world/group-readable private input defeats the point of a sealed plan.
    path = _private(tmp_path, "report.json", json.dumps({"a": 1}), mode=0o644)
    with pytest.raises(ValueError, match="permissions are too broad"):
        load_private_json(path, max_bytes=1024, label="report")


def test_a_non_object_root_is_rejected(tmp_path):
    path = _private(tmp_path, "arr.json", json.dumps([1, 2, 3]))
    with pytest.raises(ValueError, match="must be an object"):
        load_private_json(path, max_bytes=1024, label="report")


def test_an_empty_file_is_rejected_as_unbounded(tmp_path):
    path = _private(tmp_path, "empty.json", "")
    with pytest.raises(ValueError, match="not a bounded regular file"):
        load_private_json(path, max_bytes=1024, label="report")


def test_an_oversized_file_is_rejected(tmp_path):
    path = _private(tmp_path, "big.json", json.dumps({"x": "a" * 2000}))
    with pytest.raises(ValueError, match="not a bounded regular file"):
        load_private_json(path, max_bytes=100, label="report")


def test_a_directory_is_rejected_as_non_regular(tmp_path):
    with pytest.raises(ValueError, match="not a bounded regular file"):
        load_private_json(str(tmp_path), max_bytes=1024, label="report")


def test_invalid_json_propagates_as_a_value_error(tmp_path):
    # JSONDecodeError subclasses ValueError; the planner's main() catches it and fails closed.
    path = _private(tmp_path, "bad.json", "{not json")
    with pytest.raises(ValueError):
        load_private_json(path, max_bytes=1024, label="report")


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="O_NOFOLLOW unavailable on this platform")
def test_a_symlinked_input_is_not_followed(tmp_path):
    # O_NOFOLLOW makes the open fail rather than reading through a symlink into an unexpected file.
    target = _private(tmp_path, "target.json", json.dumps({"a": 1}))
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(OSError):
        load_private_json(str(link), max_bytes=1024, label="report")


# ---- CLI fails closed without leaking which private input failed ---------------------------


def test_main_fails_closed_with_a_generic_message(tmp_path, capsys):
    # A missing --report must exit 2 with a generic message -- no private path or specific cause,
    # since the inputs are secret by design.
    good = _private(tmp_path, "artifact.json", json.dumps({"composite_mean": 0.5}))
    code = main([
        "--report", str(tmp_path / "missing-report.json"),
        "--baseline-public", good, "--candidate-public", good,
        "--baseline-private", good, "--candidate-private", good,
        "--nonce", "0" * 64, "--e2e-pubkey", "AAAA",
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "benchmark seal planning failed" in err
    assert "missing-report.json" not in err
    assert "Traceback" not in err
