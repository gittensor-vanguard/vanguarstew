"""Tests for the commitment-only isolated build/QA adapter."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace

import pytest

from benchmark.sealed_aggregate import build_sealed_aggregate
from benchmark.sealed_bundle import build_sealed_bundle
from benchmark.sealed_execution import SealedExecutionPlan, SealedExecutor
from openvang.factory import ActionKind, ArtifactClass, MemoryScope, Role
from openvang.isolated import IsolatedExecutionAdapter, IsolatedExecutionError
from openvang.scheduler import FactoryScheduler, TaskStatus

CHALLENGE = "cd" * 32


def _plan(tmp_path):
    tmp_path.chmod(0o700)
    source = tmp_path / "sealed-source"
    source.mkdir(mode=0o700)
    run = source / "run"
    run.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    run.chmod(0o700)
    bundle = tmp_path / "sealed-bundle.tar"
    build_sealed_bundle(source, bundle)
    return SealedExecutionPlan(bundle_path=bundle, challenge=CHALLENGE)


def _aggregate():
    return build_sealed_aggregate(
        {
            "scored_repos": 2,
            "skipped": 1,
            "composite_mean": 0.625,
            "composite_parts": {"judge_mean": 0.75, "objective_mean": 0.5},
        },
        challenge=CHALLENGE,
    )


def _claimed_task(tmp_path, plan):
    scheduler = FactoryScheduler(tmp_path / "factory" / "scheduler.sqlite3")
    scheduler.enqueue(
        role=Role.QA,
        action=ActionKind.RUN_ISOLATED,
        input_commitment=plan.request_sha256(),
        output_scope=MemoryScope.ROLE_PRIVATE,
        output_artifact=ArtifactClass.PRIVATE_OPERATION,
    )
    task = scheduler.claim_next(Role.QA, lease_seconds=3600)
    assert task is not None
    return scheduler, task


def _adapter(scheduler, monkeypatch, result, calls):
    executor = SealedExecutor()

    def execute_approved(plan, *, approved_request_sha256):
        calls.append((plan, approved_request_sha256))
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(executor, "execute_approved", execute_approved)
    return IsolatedExecutionAdapter(scheduler, executor=executor)


def test_adapter_binds_claimed_task_approval_and_verified_aggregate_without_retaining_output(
    tmp_path, monkeypatch
):
    plan = _plan(tmp_path)
    scheduler, task = _claimed_task(tmp_path, plan)
    envelope = _aggregate()
    calls = []
    adapter = _adapter(scheduler, monkeypatch, envelope, calls)

    receipt = adapter.execute(
        task,
        plan,
        approved_request_sha256=plan.request_sha256(),
    )

    assert calls == [(plan, plan.request_sha256())]
    assert receipt.task_id == task.id
    assert receipt.input_commitment == plan.request_sha256()
    assert receipt.output_commitment == hashlib.sha256(envelope.encode("utf-8")).hexdigest()
    assert scheduler.status_counts()[TaskStatus.SUCCEEDED] == 1

    row = sqlite3.connect(scheduler.database_path).execute(
        "SELECT input_commitment, output_commitment, failure_code FROM factory_tasks WHERE id=?", (task.id,)
    ).fetchone()
    assert row == (plan.request_sha256(), receipt.output_commitment, None)
    assert envelope not in str(row)
    scheduler.close()


def test_adapter_rejects_changed_or_unapproved_plan_before_execution(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    scheduler, task = _claimed_task(tmp_path, plan)
    calls = []
    adapter = _adapter(scheduler, monkeypatch, _aggregate(), calls)

    with pytest.raises(IsolatedExecutionError, match="exact external approval"):
        adapter.execute(task, plan, approved_request_sha256="00" * 32)

    assert calls == []
    assert scheduler.status_counts()[TaskStatus.FAILED] == 1
    row = sqlite3.connect(scheduler.database_path).execute(
        "SELECT failure_code FROM factory_tasks WHERE id=?", (task.id,)
    ).fetchone()
    assert row == ("isolated-approval-rejected",)
    scheduler.close()


def test_adapter_rejects_a_plan_with_a_different_request_commitment(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    changed_plan = SealedExecutionPlan(
        bundle_path=plan.bundle_path,
        challenge=plan.challenge,
        timeout_seconds=plan.timeout_seconds + 1,
    )
    scheduler, task = _claimed_task(tmp_path, plan)
    calls = []
    adapter = _adapter(scheduler, monkeypatch, _aggregate(), calls)

    with pytest.raises(IsolatedExecutionError, match="does not match task commitment"):
        adapter.execute(
            task,
            changed_plan,
            approved_request_sha256=changed_plan.request_sha256(),
        )

    assert calls == []
    assert scheduler.status_counts()[TaskStatus.FAILED] == 1
    scheduler.close()


def test_adapter_refuses_forged_or_stale_task_before_execution(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    scheduler, task = _claimed_task(tmp_path, plan)
    calls = []
    adapter = _adapter(scheduler, monkeypatch, _aggregate(), calls)
    forged = replace(task, input_commitment="ef" * 32)

    with pytest.raises(IsolatedExecutionError, match="active claimed"):
        adapter.execute(forged, plan, approved_request_sha256=plan.request_sha256())

    assert calls == []
    assert scheduler.status_counts()[TaskStatus.RUNNING] == 1
    scheduler.close()


def test_adapter_refuses_an_expired_lease_before_execution(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    scheduler, task = _claimed_task(tmp_path, plan)
    scheduler._connection.execute(
        "UPDATE factory_tasks SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00+00:00", task.id)
    )
    calls = []
    adapter = _adapter(scheduler, monkeypatch, _aggregate(), calls)

    with pytest.raises(IsolatedExecutionError, match="active claimed"):
        adapter.execute(task, plan, approved_request_sha256=plan.request_sha256())

    assert calls == []
    assert scheduler.status_counts()[TaskStatus.RUNNING] == 1
    scheduler.close()


def test_adapter_never_persists_invalid_or_failed_sealed_output(tmp_path, monkeypatch):
    plan = _plan(tmp_path)
    scheduler, task = _claimed_task(tmp_path, plan)
    calls = []
    adapter = _adapter(scheduler, monkeypatch, '{"private":"not-an-aggregate"}', calls)

    with pytest.raises(IsolatedExecutionError, match="sealed execution failed"):
        adapter.execute(task, plan, approved_request_sha256=plan.request_sha256())

    assert calls == [(plan, plan.request_sha256())]
    assert scheduler.status_counts()[TaskStatus.FAILED] == 1
    row = sqlite3.connect(scheduler.database_path).execute(
        "SELECT output_commitment, failure_code FROM factory_tasks WHERE id=?", (task.id,)
    ).fetchone()
    assert row == (None, "sealed-execution-failed")
    scheduler.close()
