"""CLI tests for scripts/verify_attestation.py — the skeptic-facing evidence verifier.

Focus: a bad ``--transcript`` path must exit 2 with a clean, actionable message — the same
treatment ``--artifact``/``--evidence`` already get via ``_load`` — rather than crashing with a
raw traceback (#2068). ``TranscriptStore.load`` guards malformed *content* but not a bad *path*
or non-JSON bytes, so the CLI must. Drives ``run()`` end-to-end through the real load path.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.transcript import TranscriptStore  # noqa: E402
from scripts import verify_attestation  # noqa: E402


def _valid_artifact_and_evidence(tmp_path):
    """A minimal but genuine artifact + its evidence bundle, so run() reaches the transcript
    branch (the artifact/evidence loads and verify_evidence must pass first)."""
    artifact = {"composite_mean": 0.5, "per_repo": []}
    evidence = build_evidence(artifact, {"agent_commit": "abc123"})
    art_path = tmp_path / "artifact.json"
    ev_path = tmp_path / "evidence.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    return str(art_path), str(ev_path)


def test_missing_transcript_exits_two_with_clean_message(tmp_path, capsys):
    art, ev = _valid_artifact_and_evidence(tmp_path)
    missing = str(tmp_path / "does_not_exist.json")
    with pytest.raises(SystemExit) as exc:
        verify_attestation.run(["--artifact", art, "--evidence", ev, "--transcript", missing])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "cannot read transcript" in err
    assert missing in err


def test_directory_transcript_exits_two(tmp_path, capsys):
    art, ev = _valid_artifact_and_evidence(tmp_path)
    with pytest.raises(SystemExit) as exc:
        verify_attestation.run(
            ["--artifact", art, "--evidence", ev, "--transcript", str(tmp_path)])
    assert exc.value.code == 2
    assert "cannot read transcript" in capsys.readouterr().err


def test_malformed_json_transcript_exits_two(tmp_path, capsys):
    art, ev = _valid_artifact_and_evidence(tmp_path)
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        verify_attestation.run(
            ["--artifact", art, "--evidence", ev, "--transcript", str(bad)])
    assert exc.value.code == 2
    assert "cannot read transcript" in capsys.readouterr().err


def test_non_utf8_transcript_exits_two(tmp_path, capsys):
    art, ev = _valid_artifact_and_evidence(tmp_path)
    bad = tmp_path / "bytes.json"
    bad.write_bytes(b"\xff\xfe\x00\x01")
    with pytest.raises(SystemExit) as exc:
        verify_attestation.run(
            ["--artifact", art, "--evidence", ev, "--transcript", str(bad)])
    assert exc.value.code == 2
    assert "cannot read transcript" in capsys.readouterr().err


def test_valid_transcript_still_runs_and_reports(tmp_path, capsys):
    # The guard must not disturb the happy path: a readable transcript is loaded, its digest
    # compared, and the report printed (here the digests differ, so the check is False but run()
    # returns 0 without --strict).
    art, ev = _valid_artifact_and_evidence(tmp_path)
    tpath = tmp_path / "transcript.json"
    TranscriptStore([{"key": "k", "response": "r"}]).save(str(tpath))
    code = verify_attestation.run(
        ["--artifact", art, "--evidence", ev, "--transcript", str(tpath)])
    assert code == 0
    out = json.loads(capsys.readouterr().out)
    assert "transcript_digest" in out["checks"]


def _transcript_store(tag: str) -> TranscriptStore:
    store = TranscriptStore()
    store.record(
        {"model": "m", "temperature": 0,
         "messages": [{"role": "user", "content": f"prompt-{tag}"}]},
        '{"winner":"tie"}',
    )
    return store


def test_detail_from_checks_lists_every_failure():
    # Pure helper contract: every False check appears, True checks do not, and a rich
    # transcript note replaces the bare "transcript_digest FAILED" label when supplied.
    detail = verify_attestation._detail_from_checks(
        {"artifact_digest": False, "report_data": True, "transcript_digest": False},
        transcript_note="transcript_digest FAILED (recorded abc, bound def)",
    )
    assert "artifact_digest FAILED" in detail
    assert "report_data FAILED" not in detail
    assert "transcript_digest FAILED (recorded abc, bound def)" in detail
    assert verify_attestation._detail_from_checks(
        {"artifact_digest": True, "report_data": True},
    ) == "all checks passed"


def test_transcript_failure_does_not_hide_earlier_artifact_digest_failure(tmp_path, capsys):
    # #2065: tampered published artifact PLUS mismatched transcript used to overwrite detail
    # with only "transcript_digest FAILED", hiding the artifact_digest finding.
    artifact = {"composite_mean": 0.7, "per_repo": []}
    bound_store = _transcript_store("bound")
    evidence = build_evidence(artifact, {"transcript_digest": bound_store.digest()})
    evidence["artifact_digest"] = "tampered"  # published score edited after the fact

    art_path = tmp_path / "a.json"
    ev_path = tmp_path / "e.json"
    tr_path = tmp_path / "t.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    _transcript_store("published").save(str(tr_path))

    without = verify_attestation.run(["--artifact", str(art_path), "--evidence", str(ev_path)])
    without_out = json.loads(capsys.readouterr().out)
    assert without == 0
    assert without_out["ok"] is False
    assert "artifact_digest FAILED" in without_out["detail"]

    with_tr = verify_attestation.run([
        "--artifact", str(art_path), "--evidence", str(ev_path),
        "--transcript", str(tr_path),
    ])
    with_out = json.loads(capsys.readouterr().out)
    assert with_tr == 0
    assert with_out["ok"] is False
    assert with_out["checks"]["artifact_digest"] is False
    assert with_out["checks"]["transcript_digest"] is False
    assert "artifact_digest FAILED" in with_out["detail"]
    assert "transcript_digest FAILED" in with_out["detail"]


def test_transcript_only_failure_keeps_rich_detail(tmp_path, capsys):
    # Control: binding is otherwise consistent — detail should mention only the transcript miss,
    # still with the recorded/bound digest prefixes.
    artifact = {"composite_mean": 0.7, "per_repo": []}
    bound_store = _transcript_store("bound")
    evidence = build_evidence(artifact, {"transcript_digest": bound_store.digest()})

    art_path = tmp_path / "a.json"
    ev_path = tmp_path / "e.json"
    tr_path = tmp_path / "t.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    published = _transcript_store("published")
    published.save(str(tr_path))

    code = verify_attestation.run([
        "--artifact", str(art_path), "--evidence", str(ev_path),
        "--transcript", str(tr_path),
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ok"] is False
    assert out["checks"]["artifact_digest"] is True
    assert out["checks"]["transcript_digest"] is False
    assert out["detail"].startswith("transcript_digest FAILED (recorded ")
    assert "artifact_digest FAILED" not in out["detail"]


def test_matching_transcript_preserves_all_checks_passed_detail(tmp_path, capsys):
    artifact = {"composite_mean": 0.7, "per_repo": []}
    store = _transcript_store("same")
    evidence = build_evidence(artifact, {"transcript_digest": store.digest()})

    art_path = tmp_path / "a.json"
    ev_path = tmp_path / "e.json"
    tr_path = tmp_path / "t.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    store.save(str(tr_path))

    code = verify_attestation.run([
        "--artifact", str(art_path), "--evidence", str(ev_path),
        "--transcript", str(tr_path), "--strict",
    ])
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert out["ok"] is True
    assert out["checks"]["transcript_digest"] is True
    assert out["detail"] == "all checks passed"
