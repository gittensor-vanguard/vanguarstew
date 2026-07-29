"""CLI tests for scripts/verify_attestation.py — the skeptic-facing evidence verifier.

Focus: the ``--transcript`` branch must *augment* the evidence report (append its finding to the
joined detail), never *overwrite* it — otherwise an artifact/report_data/quote failure that
verify_evidence already reported is silently erased when a transcript mismatch is also present
(#2065). Drives ``run()`` end-to-end through the real transcript digest (never mocked).
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.transcript import TranscriptStore  # noqa: E402
from scripts import verify_attestation  # noqa: E402

_ARTIFACT = {"composite_mean": 0.6, "per_repo": [{"repo": "a", "tasks": 3}]}


def _transcript(path, response="ok"):
    """Write a real one-entry transcript and return (path, its digest)."""
    store = TranscriptStore()
    store.record({"model": "m-1", "messages": [{"role": "user", "content": "hi"}]}, response)
    store.save(path)
    return path, store.digest()


def _write(path, obj):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(obj, handle)
    return str(path)


def _run(capsys, *argv):
    code = verify_attestation.run(list(argv))
    out = json.loads(capsys.readouterr().out)
    return code, out


def test_matching_transcript_passes_and_keeps_all_checks_passed(tmp_path, capsys):
    tpath, tdigest = _transcript(str(tmp_path / "t.json"))
    evidence = build_evidence(_ARTIFACT, {"seed": 1, "transcript_digest": tdigest})
    artifact = _write(tmp_path / "a.json", _ARTIFACT)
    ev = _write(tmp_path / "e.json", evidence)

    code, out = _run(capsys, "--artifact", artifact, "--evidence", ev, "--transcript", tpath)
    assert code == 0
    assert out["ok"] is True
    assert out["checks"]["transcript_digest"] is True
    assert out["detail"] == "all checks passed"


def test_transcript_mismatch_alone_replaces_the_passed_sentinel(tmp_path, capsys):
    # Evidence itself is fully valid; only the supplied transcript is the wrong one.
    _, bound_digest = _transcript(str(tmp_path / "recorded.json"))
    other_path, _ = _transcript(str(tmp_path / "other.json"), response="different")
    evidence = build_evidence(_ARTIFACT, {"seed": 1, "transcript_digest": bound_digest})
    artifact = _write(tmp_path / "a.json", _ARTIFACT)
    ev = _write(tmp_path / "e.json", evidence)

    code, out = _run(capsys, "--artifact", artifact, "--evidence", ev,
                     "--transcript", other_path)
    assert out["ok"] is False
    assert out["checks"] == {"artifact_digest": True, "report_data": True,
                             "transcript_digest": False}
    # The "all checks passed" sentinel is replaced, not appended to.
    assert out["detail"].startswith("transcript_digest FAILED (recorded ")
    assert "all checks passed" not in out["detail"]


def test_transcript_mismatch_preserves_a_concurrent_evidence_failure(tmp_path, capsys):
    # The regression under test: a tampered artifact makes artifact_digest AND report_data fail;
    # a wrong transcript also fails. The detail must carry ALL THREE findings, not just the
    # transcript one -- previously the transcript branch overwrote the evidence detail.
    _, bound_digest = _transcript(str(tmp_path / "recorded.json"))
    other_path, _ = _transcript(str(tmp_path / "other.json"), response="different")
    evidence = build_evidence(_ARTIFACT, {"seed": 1, "transcript_digest": bound_digest})
    tampered = _write(tmp_path / "a.json", {**_ARTIFACT, "composite_mean": 0.99})
    ev = _write(tmp_path / "e.json", evidence)

    code, out = _run(capsys, "--artifact", tampered, "--evidence", ev,
                     "--transcript", other_path)
    assert out["ok"] is False
    assert out["checks"]["artifact_digest"] is False
    assert out["checks"]["report_data"] is False
    assert out["checks"]["transcript_digest"] is False
    # Every failing check survives in the joined detail, verify_evidence's contract preserved.
    assert "artifact_digest FAILED" in out["detail"]
    assert "report_data FAILED" in out["detail"]
    assert "transcript_digest FAILED" in out["detail"]
    # Order: the evidence findings come first, the transcript finding is appended.
    assert out["detail"].index("artifact_digest FAILED") < out["detail"].index(
        "transcript_digest FAILED")


def test_strict_exit_code_on_transcript_only_failure(tmp_path, capsys):
    _, bound_digest = _transcript(str(tmp_path / "recorded.json"))
    other_path, _ = _transcript(str(tmp_path / "other.json"), response="different")
    evidence = build_evidence(_ARTIFACT, {"seed": 1, "transcript_digest": bound_digest})
    artifact = _write(tmp_path / "a.json", _ARTIFACT)
    ev = _write(tmp_path / "e.json", evidence)

    code, _out = _run(capsys, "--artifact", artifact, "--evidence", ev,
                      "--transcript", other_path, "--strict")
    assert code == 1
