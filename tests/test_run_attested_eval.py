"""Tests for the public-only deterministic workload entrypoint."""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.transcript import TranscriptStore  # noqa: E402
from scripts import run_attested_eval as cli  # noqa: E402

COMMIT = "ab" * 20
IMAGE = f"ghcr.io/gittensor-vanguard/vanguarstew-eval@sha256:{'12' * 32}"


def _args(**overrides):
    values = {
        "repo": "/mounted/public-repo",
        "public_repo": "gittensor-vanguard/vanguarstew",
        "agent": "agent.py",
        "agent_commit": COMMIT,
        "eval_image": IMAGE,
        "model": "offline-stub-v1",
        "tasks": 2,
        "horizon": 5,
        "seed": 7,
        "rotation_seed": 11,
        "baseline": "empty",
        "transcript": None,
        "offline_stub": True,
        "memory_mode": "disabled",
        "memory_store": None,
    }
    values.update(overrides)
    return type("Args", (), values)()


def _stub_repo(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_public_repo_identity",
        lambda repo, slug: f"github.com/{slug}@{'34' * 20}",
    )


def test_offline_mode_emits_one_canonical_envelope(monkeypatch):
    _stub_repo(monkeypatch)
    seen = {}

    def replay(**kwargs):
        seen.update(kwargs)
        seen["offline_env"] = cli.os.environ["VANGUARSTEW_OFFLINE"]
        return {"tasks": 2, "composite_mean": 0.5}

    monkeypatch.setattr(cli, "run_replay", replay)
    envelope = cli.run(_args())
    parsed = json.loads(envelope)

    assert envelope == json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    assert not envelope.endswith("\n")
    assert seen["offline_env"] == "1"
    assert seen["api_key"] == "offline"
    inputs = parsed["evidence"]["inputs"]
    assert inputs == {
        "repo_set": f"github.com/gittensor-vanguard/vanguarstew@{'34' * 20}",
        "repo_set_partition": "public",
        "seed": 7,
        "rotation_seed": 11,
        "model": "offline-stub-v1",
        "agent_commit": COMMIT,
        "eval_image": IMAGE,
        "transcript_digest": TranscriptStore().digest(),
        "memory_commitment": None,
    }


def test_benchmark_memory_is_explicit_and_binds_only_its_digest(tmp_path, monkeypatch):
    _stub_repo(monkeypatch)
    seen = {}
    commitment = {
        "memory_schema_version": 1,
        "memory_policy_version": "vanguarstew-memory-v1",
        "snapshot_root": "0" * 64,
        "query_digest": "1" * 64,
        "memory_view_digest": "2" * 64,
    }

    def replay(**kwargs):
        seen.update(kwargs)
        return {"tasks": 1, "composite_mean": 0.5, "memory_commitment": commitment}

    monkeypatch.setattr(cli, "run_replay", replay)
    envelope = json.loads(
        cli.run(
            _args(memory_mode="benchmark", memory_store=str(tmp_path / "memory.sqlite"))
        )
    )
    assert type(seen["memory_provider"]).__name__ == "BenchmarkMemoryProvider"
    assert envelope["evidence"]["inputs"]["memory_commitment"] == commitment
    assert "memory.sqlite" not in json.dumps(envelope)


def test_disabled_memory_rejects_a_controller_store(monkeypatch):
    _stub_repo(monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_replay",
        lambda **kwargs: pytest.fail("scoring path must not run"),
    )
    with pytest.raises(cli.AttestedEvalError, match="memory store requires"):
        cli.run(_args(memory_store="/private/memory.sqlite"))


def test_recorded_transcript_runs_through_loopback_proxy(tmp_path, monkeypatch):
    _stub_repo(monkeypatch)
    request = {
        "model": "judge-2026-07-01",
        "temperature": 0,
        "messages": [{"role": "user", "content": "public prompt"}],
    }
    store = TranscriptStore()
    store.record(request, '{"winner":"tie"}')
    transcript = tmp_path / "transcript.json"
    store.save(str(transcript))

    def replay(**kwargs):
        assert cli.os.environ["VANGUARSTEW_OFFLINE"] == "0"
        assert kwargs["api_key"] == "transcript-replay"
        req = urllib.request.Request(
            f"{kwargs['api_base']}/chat/completions",
            method="POST",
            data=json.dumps(request).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            body = json.load(response)
        assert body["choices"][0]["message"]["content"] == '{"winner":"tie"}'
        return {"tasks": 1, "composite_mean": 0.5}

    monkeypatch.setattr(cli, "run_replay", replay)
    envelope = json.loads(
        cli.run(
            _args(
                transcript=str(transcript),
                offline_stub=False,
                tasks=1,
                model="judge-2026-07-01",
            )
        )
    )
    assert envelope["evidence"]["inputs"]["transcript_digest"] == store.digest()


@pytest.mark.parametrize(
    "overrides",
    [
        {"agent_commit": "short"},
        {"eval_image": "ghcr.io/example/eval:latest"},
        {"model": "moving model"},
        {"tasks": 0},
        {"horizon": 0},
    ],
)
def test_invalid_bound_inputs_fail_before_scoring(monkeypatch, overrides):
    _stub_repo(monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_replay",
        lambda **kwargs: pytest.fail("billable/scoring path must not run"),
    )
    with pytest.raises(cli.AttestedEvalError):
        cli.run(_args(**overrides))


def test_model_identity_must_match_replay_mode(monkeypatch):
    _stub_repo(monkeypatch)
    monkeypatch.setattr(
        cli,
        "run_replay",
        lambda **kwargs: pytest.fail("scoring path must not run"),
    )
    with pytest.raises(cli.AttestedEvalError, match="selected replay mode"):
        cli.run(_args(model="judge-2026-07-01"))
    with pytest.raises(cli.AttestedEvalError, match="selected replay mode"):
        cli.run(
            _args(
                model="offline-stub-v1",
                transcript="transcript.json",
                offline_stub=False,
            )
        )


def test_unscored_artifact_fails_closed(monkeypatch):
    _stub_repo(monkeypatch)
    monkeypatch.setattr(cli, "run_replay", lambda **kwargs: {"tasks": 0, "error": "no tasks"})
    with pytest.raises(cli.AttestedEvalError, match="did not produce"):
        cli.run(_args())


@pytest.mark.parametrize(
    "origin",
    [
        "https://github.com/gittensor-vanguard/vanguarstew.git",
        "git@github.com:gittensor-vanguard/vanguarstew.git",
        "ssh://git@github.com/gittensor-vanguard/vanguarstew",
    ],
)
def test_public_identity_accepts_canonical_github_origins(monkeypatch, origin):
    def fake_git(repo, *args):
        return origin if args[0] == "remote" else "56" * 20

    monkeypatch.setattr(cli, "_git", fake_git)
    assert cli._public_repo_identity("/repo", "gittensor-vanguard/vanguarstew") == (
        f"github.com/gittensor-vanguard/vanguarstew@{'56' * 20}"
    )


def test_public_identity_rejects_mismatch_or_non_github_origin(monkeypatch):
    monkeypatch.setattr(cli, "_git", lambda repo, *args: "file:///private/repo")
    with pytest.raises(cli.AttestedEvalError):
        cli._public_repo_identity("/repo", "gittensor-vanguard/vanguarstew")

    monkeypatch.setattr(
        cli,
        "_git",
        lambda repo, *args: (
            "https://github.com/other/repo.git" if args[0] == "remote" else "56" * 20
        ),
    )
    with pytest.raises(cli.AttestedEvalError, match="does not match"):
        cli._public_repo_identity("/repo", "gittensor-vanguard/vanguarstew")


def test_main_sanitizes_failure_and_never_writes_partial_stdout(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda args: (_ for _ in ()).throw(RuntimeError("secret")))
    result = cli.main(
        [
            "--repo",
            "/private/path",
            "--public-repo",
            "owner/repo",
            "--agent-commit",
            COMMIT,
            "--eval-image",
            IMAGE,
            "--model",
            "offline-stub-v1",
            "--offline-stub",
        ]
    )
    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "attested eval failed\n"
    assert "secret" not in captured.err and "/private/path" not in captured.err
