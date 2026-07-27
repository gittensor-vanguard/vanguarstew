"""Tests for approval-bound, network-isolated sealed execution."""

import json
import os
import pathlib
import stat
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from benchmark.sealed_aggregate import verify_sealed_aggregate  # noqa: E402
from benchmark.sealed_bundle import build_sealed_bundle  # noqa: E402
from benchmark.sealed_execution import (  # noqa: E402
    SealedExecutionError,
    SealedExecutionPlan,
    SealedExecutor,
)
from scripts.plan_sealed_execution import build_plan  # noqa: E402
from scripts.run_sealed_bundle import main as run_main  # noqa: E402
from scripts.sealed_network_exec import network_namespace_isolated  # noqa: E402

CHALLENGE = "ab" * 32


def _bundle(tmp_path, *, name="bundle.tar"):
    source = tmp_path / f"source-{name}"
    source.mkdir(mode=0o700)
    source.chmod(0o700)
    run = source / "run"
    run.write_bytes(b"#!/bin/sh\nexit 99\n")
    run.chmod(0o700)
    data = source / "input.json"
    data.write_bytes(b'{"identity":"forbidden-identity-marker"}\n')
    data.chmod(0o600)
    output = tmp_path / name
    build_sealed_bundle(source, output)
    return output


def _artifact():
    return {
        "repos": 3,
        "scored_repos": 2,
        "skipped": 1,
        "composite_mean": 0.625,
        "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.5},
        "per_repo": [{"repo": "forbidden-identity-marker", "rows": ["sensitive-row"]}],
        "error": "sensitive-error",
    }


def _write_output(path, value):
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def test_execution_plan_is_offline_content_bound_and_omits_local_metadata(tmp_path):
    bundle = _bundle(tmp_path)
    plan = SealedExecutionPlan(bundle_path=bundle, challenge=CHALLENGE)
    summary = plan.approval_summary()
    rendered = json.dumps(summary, sort_keys=True)
    assert summary["execution_performed"] is False
    assert summary["request_sha256"] == plan.request_sha256()
    assert summary["request"]["result_contract"] == "sealed-aggregate-v1"
    assert summary["request"]["network_policy"] == "new-linux-user-network-namespace-v1"
    assert "shared-host-mounts" in summary["request"]["filesystem_policy"]
    assert str(bundle) not in rendered
    assert "payload/run" not in rendered
    assert all(summary["privacy"].values())
    assert all(summary["limitations"].values())


def test_execution_planner_reads_no_credentials_and_makes_no_request(tmp_path):
    bundle = _bundle(tmp_path)
    plan = build_plan(["--bundle", str(bundle), "--challenge", CHALLENGE])
    assert plan.challenge == CHALLENGE
    assert plan.approval_summary()["execution_performed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"challenge": "AB" * 32},
        {"timeout_seconds": 0},
        {"timeout_seconds": True},
        {"max_output_bytes": 100},
        {"max_memory_bytes": 64 * 1024 * 1024},
    ],
)
def test_execution_plan_rejects_malformed_limits_and_challenge(tmp_path, change):
    values = {"bundle_path": _bundle(tmp_path), "challenge": CHALLENGE}
    values.update(change)
    with pytest.raises(SealedExecutionError):
        SealedExecutionPlan(**values)


def test_execution_requires_exact_approval_before_process_or_extraction(tmp_path):
    calls = []
    plan = SealedExecutionPlan(bundle_path=_bundle(tmp_path), challenge=CHALLENGE)
    with pytest.raises(SealedExecutionError, match="approved"):
        SealedExecutor(
            process_executor=lambda *args, **kwargs: calls.append((args, kwargs)), geteuid=lambda: 1
        ).execute_approved(
            plan,
            approved_request_sha256="00" * 32,
        )
    assert calls == []
    assert not list(tmp_path.glob(".sealed-run-*"))


def test_execution_refuses_host_root_even_with_matching_approval(tmp_path):
    plan = SealedExecutionPlan(bundle_path=_bundle(tmp_path), challenge=CHALLENGE)
    with pytest.raises(SealedExecutionError, match="unprivileged"):
        SealedExecutor(
            process_executor=lambda *args, **kwargs: pytest.fail("must not run"), geteuid=lambda: 0
        ).execute_approved(
            plan,
            approved_request_sha256=plan.request_sha256(),
        )


def test_execution_uses_fresh_namespaces_minimal_env_and_returns_only_aggregate(tmp_path):
    seen = {}

    def process_executor(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        assert (kwargs["cwd"] / "payload" / "run").is_file()
        _write_output(kwargs["output_path"], json.dumps(_artifact()))
        return 0

    plan = SealedExecutionPlan(bundle_path=_bundle(tmp_path), challenge=CHALLENGE)
    envelope = SealedExecutor(
        process_executor=process_executor, geteuid=lambda: 1
    ).execute_approved(
        plan,
        approved_request_sha256=plan.request_sha256(),
    )
    assert verify_sealed_aggregate(envelope, expected_challenge=CHALLENGE)["ok"] is True
    assert "forbidden-identity-marker" not in envelope
    assert "sensitive" not in envelope
    argv = seen["argv"]
    assert argv[0] == "/usr/bin/unshare"
    for option in (
        "--user",
        "--map-root-user",
        "--net",
        "--ipc",
        "--uts",
        "--mount",
        "--pid",
        "--fork",
        "--mount-proc",
    ):
        assert option in argv
    assert "--kill-child=SIGKILL" in argv
    assert set(seen["env"]) == {
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "PYTHONHASHSEED",
        "SEALED_RESULT_CHALLENGE",
        "SOURCE_DATE_EPOCH",
        "TMPDIR",
        "VANGUARSTEW_OFFLINE",
    }
    assert seen["env"]["VANGUARSTEW_OFFLINE"] == "1"
    assert seen["env"]["SEALED_RESULT_CHALLENGE"] == CHALLENGE
    assert "SSH_AUTH_SOCK" not in seen["env"]
    assert not list(tmp_path.glob(".sealed-run-*"))


def test_execution_detects_bundle_change_after_approval(tmp_path):
    bundle = _bundle(tmp_path)
    plan = SealedExecutionPlan(bundle_path=bundle, challenge=CHALLENGE)
    with bundle.open("ab") as handle:
        handle.write(b"trailing-change")
    bundle.chmod(0o600)
    with pytest.raises(SealedExecutionError, match="changed"):
        SealedExecutor(
            process_executor=lambda *args, **kwargs: pytest.fail("must not run"), geteuid=lambda: 1
        ).execute_approved(
            plan,
            approved_request_sha256=plan.request_sha256(),
        )


@pytest.mark.parametrize("behavior", ["exit", "raise", "invalid", "empty", "broad-mode", "symlink"])
def test_execution_fails_without_rendering_workload_output_or_paths(tmp_path, behavior):
    def process_executor(argv, **kwargs):
        if behavior == "raise":
            raise RuntimeError("forbidden-identity-marker")
        if behavior == "invalid":
            _write_output(kwargs["output_path"], '{"detail":"forbidden-identity-marker"}')
        if behavior == "empty":
            _write_output(kwargs["output_path"], "")
        if behavior == "broad-mode":
            _write_output(kwargs["output_path"], json.dumps(_artifact()))
            kwargs["output_path"].chmod(0o644)
        if behavior == "symlink":
            target = kwargs["cwd"] / "payload" / "input.json"
            kwargs["output_path"].symlink_to(target)
        return 1 if behavior == "exit" else 0

    bundle = _bundle(tmp_path)
    plan = SealedExecutionPlan(bundle_path=bundle, challenge=CHALLENGE)
    with pytest.raises(SealedExecutionError) as raised:
        SealedExecutor(process_executor=process_executor, geteuid=lambda: 1).execute_approved(
            plan,
            approved_request_sha256=plan.request_sha256(),
        )
    rendered = str(raised.value)
    assert "forbidden-identity-marker" not in rendered
    assert str(bundle) not in rendered
    assert not list(tmp_path.glob(".sealed-run-*"))


def test_run_cli_approval_failure_is_constant(tmp_path, capsys):
    bundle = _bundle(tmp_path, name="forbidden-identity-marker.tar")
    result = run_main(
        [
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
    assert captured.err == "sealed bundle execution failed\n"
    assert "forbidden-identity-marker" not in captured.err


def test_network_namespace_gate_requires_only_loopback_routes(tmp_path):
    interfaces = tmp_path / "interfaces"
    interfaces.mkdir()
    (interfaces / "lo").mkdir()
    routes = tmp_path / "route"
    routes.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n", encoding="ascii"
    )
    assert network_namespace_isolated(interfaces_path=interfaces, route_path=routes) is True

    (interfaces / "eth0").mkdir()
    assert network_namespace_isolated(interfaces_path=interfaces, route_path=routes) is False
    (interfaces / "eth0").rmdir()
    routes.write_text(
        "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
        "eth0 00000000 0100007F 0003 0 0 0 00000000 0 0 0\n",
        encoding="ascii",
    )
    assert network_namespace_isolated(interfaces_path=interfaces, route_path=routes) is False


def test_bundle_and_output_files_remain_restricted_in_test_fixture(tmp_path):
    bundle = _bundle(tmp_path)
    assert stat.S_IMODE(bundle.stat().st_mode) == 0o600
    assert os.name == "nt" or not bundle.stat().st_mode & 0o077
