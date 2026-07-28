"""Tests for target-bound, approval-gated sealed execution over pinned SSH."""

import json
import pathlib
import stat
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_aggregate import build_sealed_aggregate, verify_sealed_aggregate  # noqa: E402
from benchmark.sealed_bundle import build_sealed_bundle  # noqa: E402
from benchmark.sealed_remote import (  # noqa: E402
    SealedRemoteError,
    SealedRemoteExecutionPlan,
    SealedRemoteExecutor,
    load_owner_detail,
    owner_target_binding,
)
from benchmark.sealed_runtime import build_sealed_runtime  # noqa: E402
from benchmark.sealed_ssh import SealedSSHConnection  # noqa: E402
from scripts.plan_sealed_remote import build_plan  # noqa: E402
from scripts.run_sealed_remote import main as run_main  # noqa: E402

SOURCE_ROOT = pathlib.Path(__file__).resolve().parents[1]
CHALLENGE = "ab" * 32


def _restricted_file(tmp_path, name, content):
    path = tmp_path / name
    path.write_bytes(content)
    path.chmod(0o600)
    return path


def _detail():
    return {
        "id": "sandbox-neutral-123",
        "ssh_host": "example.invalid",
        "ssh_port": 2222,
        "ssh_user": "worker",
        "ignored": "forbidden-identity-marker",
    }


def _detail_file(tmp_path, detail=None):
    return _restricted_file(
        tmp_path,
        "owner-detail.json",
        json.dumps(detail or _detail()).encode("utf-8"),
    )


def _connection(tmp_path, detail=None):
    detail = detail or _detail()
    identity = _restricted_file(tmp_path, "identity", b"identity-placeholder")
    known_hosts = _known_hosts(tmp_path)
    return (
        SealedSSHConnection.from_owner_detail(
            detail,
            identity_file=identity,
            known_hosts_file=known_hosts,
        ),
        identity,
        known_hosts,
    )


def _known_hosts(tmp_path):
    path = tmp_path / "known_hosts"
    if not path.exists():
        _restricted_file(tmp_path, "known_hosts", b"example.invalid ssh-ed25519 AAAA\n")
    return path


def _bundle(tmp_path):
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    source.chmod(0o700)
    run = source / "run"
    run.write_bytes(b"#!/bin/sh\nexit 99\n")
    run.chmod(0o700)
    payload = source / "input.json"
    payload.write_bytes(b'{"identity":"forbidden-identity-marker"}\n')
    payload.chmod(0o600)
    bundle = tmp_path / "payload.tar"
    build_sealed_bundle(source, bundle)
    return bundle


def _runtime(tmp_path):
    runtime = tmp_path / "runtime.pyz"
    build_sealed_runtime(SOURCE_ROOT, runtime)
    return runtime


def _plan(tmp_path, detail=None):
    detail = detail or _detail()
    return SealedRemoteExecutionPlan(
        runtime_path=_runtime(tmp_path),
        bundle_path=_bundle(tmp_path),
        challenge=CHALLENGE,
        target_binding_sha256=owner_target_binding(detail, _known_hosts(tmp_path)),
    )


def _artifact():
    return {
        "repos": 3,
        "scored_repos": 2,
        "skipped": 1,
        "composite_mean": 0.625,
        "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.5},
        "per_repo": [{"repo": "forbidden-identity-marker"}],
    }


def test_owner_detail_loader_requires_private_file_and_ignores_extra_fields(tmp_path):
    path = _detail_file(tmp_path)
    assert load_owner_detail(path)["id"] == "sandbox-neutral-123"
    path.chmod(0o644)
    with pytest.raises(SealedRemoteError, match="group or others"):
        load_owner_detail(path)


def test_remote_plan_binds_target_runtime_payload_and_omits_sensitive_metadata(tmp_path):
    detail = _detail()
    plan = _plan(tmp_path, detail)
    summary = plan.approval_summary()
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["network_request_made"] is False
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["request"]["target_binding_sha256"] == owner_target_binding(
        detail, _known_hosts(tmp_path)
    )
    assert summary["request"]["execution_request_sha256"] == plan.execution_request_sha256
    assert len(summary["request"]["runtime_source_revision"]) == 40
    assert summary["request"]["result_contract"] == "sealed-aggregate-v1"
    assert all(summary["preconditions"].values())
    assert all(summary["privacy"].values())
    assert all(summary["limitations"].values())
    assert detail["id"] not in rendered
    assert detail["ssh_host"] not in rendered
    assert str(plan.runtime_path) not in rendered
    assert str(plan.bundle_path) not in rendered
    assert "forbidden-identity-marker" not in rendered


def test_remote_planner_is_offline_and_reads_restricted_owner_detail(tmp_path):
    detail_file = _detail_file(tmp_path)
    runtime = _runtime(tmp_path)
    bundle = _bundle(tmp_path)
    plan = build_plan(
        [
            "--owner-detail-file",
            str(detail_file),
            "--known-hosts-file",
            str(_known_hosts(tmp_path)),
            "--runtime",
            str(runtime),
            "--bundle",
            str(bundle),
            "--challenge",
            CHALLENGE,
        ]
    )
    assert plan.target_binding_sha256 == owner_target_binding(_detail(), _known_hosts(tmp_path))
    assert plan.approval_summary()["network_request_made"] is False


def test_remote_execution_requires_exact_approval_before_ssh(tmp_path):
    calls = []
    detail = _detail()
    connection, _, _ = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    with pytest.raises(SealedRemoteError, match="approved"):
        SealedRemoteExecutor(
            runner=lambda *args, **kwargs: calls.append((args, kwargs))
        ).execute_approved(
            connection,
            plan,
            owner_detail=detail,
            approved_request_sha256="00" * 32,
        )
    assert calls == []


def test_remote_execution_rejects_target_mismatch_before_ssh(tmp_path):
    calls = []
    detail = _detail()
    other = dict(detail, id="sandbox-other-456")
    connection, _, _ = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    with pytest.raises(SealedRemoteError, match="target"):
        SealedRemoteExecutor(
            runner=lambda *args, **kwargs: calls.append((args, kwargs))
        ).execute_approved(
            connection,
            plan,
            owner_detail=other,
            approved_request_sha256=plan.request_sha256(),
        )
    assert calls == []


def test_remote_execution_rejects_changed_host_key_binding_before_ssh(tmp_path):
    calls = []
    detail = _detail()
    connection, _, known_hosts = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    known_hosts.write_bytes(b"example.invalid ssh-ed25519 changed\n")
    known_hosts.chmod(0o600)
    with pytest.raises(SealedRemoteError, match="target"):
        SealedRemoteExecutor(
            runner=lambda *args, **kwargs: calls.append((args, kwargs))
        ).execute_approved(
            connection,
            plan,
            owner_detail=detail,
            approved_request_sha256=plan.request_sha256(),
        )
    assert calls == []


def test_remote_execution_verifies_staged_payload_runs_fixed_runtime_and_cleans(tmp_path):
    calls = []
    detail = _detail()
    connection, _, _ = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    envelope = build_sealed_aggregate(_artifact(), challenge=CHALLENGE).encode("utf-8")

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        command = argv[-1]
        stdout = envelope if "exec env -i" in command else b""
        return SimpleNamespace(returncode=0, stdout=stdout)

    result = SealedRemoteExecutor(runner=runner).execute_approved(
        connection,
        plan,
        owner_detail=detail,
        approved_request_sha256=plan.request_sha256(),
    )
    assert verify_sealed_aggregate(result, expected_challenge=CHALLENGE)["ok"] is True
    assert "forbidden-identity-marker" not in result
    assert len(calls) == 5
    commands = [call[0][-1] for call in calls]
    assert "sha256sum -c" in commands[0]
    assert plan.remote_bundle in commands[0]
    assert "cat >" in commands[1]
    assert calls[1][1]["input"] == plan.runtime_path.read_bytes()
    assert "sha256sum -c" in commands[2]
    assert "exec env -i" in commands[3]
    assert f"--runtime-sha256 {plan.runtime_sha256}" in commands[3]
    assert f"--approved-request-sha256 {plan.execution_request_sha256}" in commands[3]
    assert "rm -f" in commands[4]
    assert plan.remote_runtime in commands[4]
    assert plan.remote_bundle in commands[4]
    assert all(call[1]["max_stdout_bytes"] == 4096 for call in calls)


def test_remote_execution_detects_runtime_change_before_ssh(tmp_path):
    calls = []
    detail = _detail()
    connection, _, _ = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    with plan.runtime_path.open("ab") as handle:
        handle.write(b"changed")
    plan.runtime_path.chmod(0o600)
    with pytest.raises(SealedRemoteError, match="changed"):
        SealedRemoteExecutor(
            runner=lambda *args, **kwargs: calls.append((args, kwargs))
        ).execute_approved(
            connection,
            plan,
            owner_detail=detail,
            approved_request_sha256=plan.request_sha256(),
        )
    assert calls == []


@pytest.mark.parametrize("failure", ["execute", "aggregate", "cleanup"])
def test_remote_failures_are_constant_and_cleanup_is_attempted(tmp_path, failure):
    calls = []
    detail = _detail()
    connection, _, _ = _connection(tmp_path, detail)
    plan = _plan(tmp_path, detail)
    envelope = build_sealed_aggregate(_artifact(), challenge=CHALLENGE).encode("utf-8")

    def runner(argv, **kwargs):
        calls.append((argv, kwargs))
        command = argv[-1]
        if failure == "execute" and "exec env -i" in command:
            raise RuntimeError("forbidden-identity-marker")
        if failure == "cleanup" and "rm -f" in command:
            return SimpleNamespace(returncode=1, stdout=b"forbidden-identity-marker")
        if "exec env -i" in command:
            stdout = (
                b'{"detail":"forbidden-identity-marker"}' if failure == "aggregate" else envelope
            )
            return SimpleNamespace(returncode=0, stdout=stdout)
        return SimpleNamespace(returncode=0, stdout=b"")

    with pytest.raises(SealedRemoteError) as raised:
        SealedRemoteExecutor(runner=runner).execute_approved(
            connection,
            plan,
            owner_detail=detail,
            approved_request_sha256=plan.request_sha256(),
        )
    assert "forbidden-identity-marker" not in str(raised.value)
    assert "example.invalid" not in str(raised.value)
    assert any("rm -f" in call[0][-1] for call in calls)


def test_remote_cli_approval_failure_is_constant_and_makes_no_ssh_request(tmp_path, capsys):
    detail_file = _detail_file(tmp_path)
    connection, identity, known_hosts = _connection(tmp_path)
    assert connection.host == "example.invalid"
    runtime = _runtime(tmp_path)
    bundle = _bundle(tmp_path)
    result = run_main(
        [
            "--owner-detail-file",
            str(detail_file),
            "--identity-file",
            str(identity),
            "--known-hosts-file",
            str(known_hosts),
            "--runtime",
            str(runtime),
            "--bundle",
            str(bundle),
            "--challenge",
            CHALLENGE,
            "--approved-request-sha256",
            "00" * 32,
        ]
    )
    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert captured.err == "sealed remote execution failed\n"
    assert "example.invalid" not in captured.err
    assert "forbidden-identity-marker" not in captured.err


def test_remote_artifacts_remain_private_in_test_fixture(tmp_path):
    plan = _plan(tmp_path)
    assert stat.S_IMODE(plan.runtime_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(plan.bundle_path.stat().st_mode) == 0o600
