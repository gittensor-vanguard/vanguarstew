"""Tests for approval-bound, pinned-host sealed SSH staging."""

import json
import os
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_ssh import (  # noqa: E402
    SealedSSHConnection,
    SealedSSHDeploymentPlan,
    SealedSSHError,
    SealedSSHTransport,
)
from scripts.plan_sealed_ssh import build_plan  # noqa: E402

CHALLENGE = "ab" * 32


def _restricted_file(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _connection(tmp_path):
    identity = _restricted_file(tmp_path, "identity", b"identity-placeholder")
    known_hosts = _restricted_file(tmp_path, "known_hosts", b"example.invalid ssh-ed25519 AAAA\n")
    return SealedSSHConnection.from_owner_detail(
        {
            "ssh_host": "example.invalid",
            "ssh_port": 2222,
            "ssh_user": "worker",
            "ignored": "must-not-be-read",
        },
        identity_file=identity,
        known_hosts_file=known_hosts,
    )


def _plan(tmp_path, content=b"bounded archive bytes"):
    bundle = _restricted_file(tmp_path, "payload.tar", content)
    return SealedSSHDeploymentPlan(bundle_path=bundle, challenge=CHALLENGE)


def test_connection_uses_only_owner_ssh_fields_and_repr_is_redacted(tmp_path):
    connection = _connection(tmp_path)
    assert repr(connection) == "SealedSSHConnection(<redacted>)"
    assert "example.invalid" not in repr(connection)
    argv = connection.ssh_argv("true")
    assert "BatchMode=yes" in argv
    assert "IdentitiesOnly=yes" in argv
    assert "StrictHostKeyChecking=yes" in argv
    assert "ForwardAgent=no" in argv
    assert "ClearAllForwardings=yes" in argv
    assert "RequestTTY=no" in argv
    assert "accept-new" not in argv


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.parametrize("file_name", ["identity", "known_hosts"])
def test_connection_rejects_files_visible_to_other_users(tmp_path, file_name):
    identity = _restricted_file(tmp_path, "identity", b"identity-placeholder")
    known_hosts = _restricted_file(tmp_path, "known_hosts", b"host key\n")
    {"identity": identity, "known_hosts": known_hosts}[file_name].chmod(0o644)
    with pytest.raises(SealedSSHError, match="group or others"):
        SealedSSHConnection(
            host="example.invalid",
            port=22,
            user="worker",
            identity_file=identity,
            known_hosts_file=known_hosts,
        )


def test_connection_requires_a_prepopulated_known_hosts_file(tmp_path):
    identity = _restricted_file(tmp_path, "identity", b"identity-placeholder")
    known_hosts = tmp_path / "known_hosts"
    known_hosts.touch(mode=0o600)
    with pytest.raises(SealedSSHError, match="non-empty"):
        SealedSSHConnection(
            host="example.invalid",
            port=22,
            user="worker",
            identity_file=identity,
            known_hosts_file=known_hosts,
        )


def test_connection_rejects_missing_owner_fields_without_rendering_detail(tmp_path):
    identity = _restricted_file(tmp_path, "identity", b"identity-placeholder")
    known_hosts = _restricted_file(tmp_path, "known_hosts", b"host key\n")
    detail = {"sensitive_error": "must-not-be-rendered"}
    with pytest.raises(SealedSSHError) as raised:
        SealedSSHConnection.from_owner_detail(
            detail,
            identity_file=identity,
            known_hosts_file=known_hosts,
        )
    assert "must-not-be-rendered" not in str(raised.value)


def test_offline_plan_binds_content_challenge_and_omits_local_metadata(tmp_path):
    plan = _plan(tmp_path)
    summary = plan.approval_summary()
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["network_request_made"] is False
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["request"]["bundle_sha256"] == plan.bundle_sha256
    assert summary["request"]["result_contract"] == "sealed-aggregate-v1"
    assert str(plan.bundle_path) not in rendered
    assert "example.invalid" not in rendered
    assert all(summary["privacy"].values())


def test_planner_reads_the_bundle_without_network(tmp_path):
    bundle = _restricted_file(tmp_path, "payload.tar", b"payload")
    plan = build_plan(["--bundle", str(bundle), "--challenge", CHALLENGE])
    assert plan.bundle_bytes == 7
    assert plan.approval_summary()["network_request_made"] is False


def test_stage_requires_exact_approval_before_starting_ssh(tmp_path):
    calls = []
    transport = SealedSSHTransport(runner=lambda *args, **kwargs: calls.append((args, kwargs)))
    with pytest.raises(SealedSSHError, match="approved"):
        transport.stage_approved(
            _connection(tmp_path),
            _plan(tmp_path),
            approved_request_sha256="00" * 32,
        )
    assert calls == []


def test_stage_uploads_hash_checks_and_never_executes_the_payload(tmp_path):
    calls = []

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    plan = _plan(tmp_path)
    result = SealedSSHTransport(timeout=9, runner=runner).stage_approved(
        _connection(tmp_path),
        plan,
        approved_request_sha256=plan.request_sha256(),
    )
    assert result == {
        "staged": True,
        "remote_execution_performed": False,
    }
    assert len(calls) == 2
    assert calls[0][1]["input"] == b"bounded archive bytes"
    assert calls[1][1]["input"] is None
    assert all(call[1]["capture_output"] is True for call in calls)
    assert all(call[1]["check"] is False for call in calls)
    assert all(call[1]["timeout"] == 9.0 for call in calls)
    remote_commands = [call[0][-1] for call in calls]
    assert "cat >" in remote_commands[0]
    assert "sha256sum -c" in remote_commands[1]
    assert all("tar -" not in command for command in remote_commands)
    assert all("python" not in command for command in remote_commands)


def test_stage_detects_a_bundle_changed_after_approval(tmp_path):
    plan = _plan(tmp_path)
    plan.bundle_path.write_bytes(b"changed")
    plan.bundle_path.chmod(0o600)
    with pytest.raises(SealedSSHError, match="changed"):
        SealedSSHTransport(
            runner=lambda *args, **kwargs: pytest.fail("must not run")
        ).stage_approved(
            _connection(tmp_path),
            plan,
            approved_request_sha256=plan.request_sha256(),
        )


def test_stage_discards_remote_output_and_connection_metadata_on_failure(tmp_path):
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired("ssh-to-sensitive-host", 1, output=b"sensitive-output")

    plan = _plan(tmp_path)
    with pytest.raises(SealedSSHError) as raised:
        SealedSSHTransport(runner=runner).stage_approved(
            _connection(tmp_path),
            plan,
            approved_request_sha256=plan.request_sha256(),
        )
    rendered = str(raised.value)
    assert "sensitive-host" not in rendered
    assert "sensitive-output" not in rendered
