"""Tests for the offline attestation-evidence verifier CLI."""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.attestation import build_evidence  # noqa: E402
from benchmark.transcript import TranscriptStore  # noqa: E402
from scripts import verify_attestation as cli  # noqa: E402


def _artifact():
    return {"composite_mean": 0.8, "scored_repos": 1, "tasks": 2}


def _transcript_store(tag="a"):
    store = TranscriptStore()
    store.record(
        {"model": "judge-2026-07-01", "temperature": 0,
         "messages": [{"role": "user", "content": f"prompt-{tag}"}]},
        '{"winner":"tie"}',
    )
    return store


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle)


def _setup(tmp_path, artifact, evidence, store):
    artifact_path = tmp_path / "artifact.json"
    evidence_path = tmp_path / "evidence.json"
    transcript_path = tmp_path / "transcript.json"
    _write_json(artifact_path, artifact)
    _write_json(evidence_path, evidence)
    store.save(str(transcript_path))
    return str(artifact_path), str(evidence_path), str(transcript_path)


def test_transcript_failure_does_not_hide_an_earlier_artifact_digest_failure(tmp_path, capsys):
    # #2065: a tampered artifact PLUS a mismatched transcript used to report ONLY
    # "transcript_digest FAILED" -- the artifact_digest failure that verify_evidence() already
    # found was silently overwritten and dropped from `detail`.
    artifact = _artifact()
    recorded_store = _transcript_store("recorded")
    evidence = build_evidence(artifact, {"transcript_digest": recorded_store.digest()})

    tampered_artifact = dict(artifact, composite_mean=0.99)  # published artifact edited after
    published_store = _transcript_store("published")  # different transcript than was bound

    artifact_path, evidence_path, transcript_path = _setup(
        tmp_path, tampered_artifact, evidence, published_store)

    exit_code = cli.run([
        "--artifact", artifact_path, "--evidence", evidence_path,
        "--transcript", transcript_path,
    ])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0  # --strict not passed
    assert out["ok"] is False
    assert out["checks"]["artifact_digest"] is False
    assert out["checks"]["transcript_digest"] is False
    assert "artifact_digest FAILED" in out["detail"]
    assert "transcript_digest FAILED" in out["detail"]


def test_transcript_only_failure_reports_only_that_check(tmp_path, capsys):
    # Control: when the artifact/evidence binding is otherwise consistent, only the transcript
    # mismatch should show up in `detail`.
    artifact = _artifact()
    recorded_store = _transcript_store("recorded")
    evidence = build_evidence(artifact, {"transcript_digest": recorded_store.digest()})
    published_store = _transcript_store("published")

    artifact_path, evidence_path, transcript_path = _setup(
        tmp_path, artifact, evidence, published_store)

    exit_code = cli.run([
        "--artifact", artifact_path, "--evidence", evidence_path,
        "--transcript", transcript_path,
    ])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["ok"] is False
    assert out["checks"]["artifact_digest"] is True
    assert out["checks"]["transcript_digest"] is False
    assert out["detail"] == "transcript_digest FAILED"


def test_no_transcript_flag_behavior_is_unchanged(tmp_path, capsys):
    # Control: omitting --transcript entirely must leave verify_evidence()'s own report untouched.
    artifact = _artifact()
    evidence = build_evidence(artifact, {})
    artifact_path = tmp_path / "artifact.json"
    evidence_path = tmp_path / "evidence.json"
    _write_json(artifact_path, artifact)
    _write_json(evidence_path, evidence)

    exit_code = cli.run(["--artifact", str(artifact_path), "--evidence", str(evidence_path)])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["ok"] is True
    assert "transcript_digest" not in out["checks"]
    assert out["detail"] == "all checks passed"


def test_matching_transcript_reports_all_checks_passed(tmp_path, capsys):
    # Control: a transcript that matches the bound digest keeps `ok` True and the "all checks
    # passed" detail, alongside the earlier artifact/evidence checks.
    artifact = _artifact()
    store = _transcript_store("matching")
    evidence = build_evidence(artifact, {"transcript_digest": store.digest()})

    artifact_path, evidence_path, transcript_path = _setup(tmp_path, artifact, evidence, store)

    exit_code = cli.run([
        "--artifact", artifact_path, "--evidence", evidence_path,
        "--transcript", transcript_path,
    ])
    out = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert out["ok"] is True
    assert out["checks"]["transcript_digest"] is True
    assert out["detail"] == "all checks passed"


def test_strict_exits_1_when_transcript_check_fails(tmp_path, capsys):
    artifact = _artifact()
    recorded_store = _transcript_store("recorded")
    evidence = build_evidence(artifact, {"transcript_digest": recorded_store.digest()})
    published_store = _transcript_store("published")

    artifact_path, evidence_path, transcript_path = _setup(
        tmp_path, artifact, evidence, published_store)

    exit_code = cli.run([
        "--artifact", artifact_path, "--evidence", evidence_path,
        "--transcript", transcript_path, "--strict",
    ])
    capsys.readouterr()

    assert exit_code == 1
