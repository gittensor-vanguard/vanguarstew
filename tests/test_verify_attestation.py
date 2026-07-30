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


def test_non_mapping_inputs_warns_and_reports_digest_mismatch(tmp_path, capsys):
    # #2251: a truthy non-dict `inputs` (e.g. a list) used to raise AttributeError on `.get`
    # inside the --transcript branch. Mirror build_evidence: warn, treat as empty, and let the
    # digest check report False / exit 0 (without --strict) instead of crashing.
    #
    # Shape mirrors a published bundle that still passes verify_evidence: digests were computed
    # as if inputs were empty (the writer's tolerant path), then `inputs` was stored as a list.
    artifact = {"composite_mean": 0.5, "per_repo": []}
    evidence = build_evidence(artifact, ["not", "a", "mapping"])
    evidence["inputs"] = ["not", "a", "mapping"]
    art_path = tmp_path / "artifact.json"
    ev_path = tmp_path / "evidence.json"
    art_path.write_text(json.dumps(artifact), encoding="utf-8")
    ev_path.write_text(json.dumps(evidence), encoding="utf-8")
    tpath = tmp_path / "transcript.json"
    TranscriptStore([{"key": "k", "response": "r"}]).save(str(tpath))

    # Without --transcript the same bundle already verifies (baseline from the issue).
    assert verify_attestation.run(
        ["--artifact", str(art_path), "--evidence", str(ev_path)]) == 0
    capsys.readouterr()

    code = verify_attestation.run(
        ["--artifact", str(art_path), "--evidence", str(ev_path),
         "--transcript", str(tpath)])
    assert code == 0
    captured = capsys.readouterr()
    assert "inputs is list, not a dict; treating as empty" in captured.err
    out = json.loads(captured.out)
    assert out["checks"]["transcript_digest"] is False
