"""Tests for the commitment-only read-only subnet adapter."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from openvang.factory import ActionKind, ArtifactClass, MemoryScope, Role
from openvang.scheduler import FactoryScheduler, TaskStatus
from openvang.subnet import ReadOnlySubnetStateAdapter, SubnetStateError, SubnetStatePlan


class _Source:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []

    def read_snapshot(self, plan):
        self.calls.append(plan)
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return self.snapshot


def _plan(*, network="finney", netuid=42):
    return SubnetStatePlan(network=network, netuid=netuid)


def _snapshot(plan):
    return {
        "schema_version": 1,
        "network": plan.network,
        "netuid": plan.netuid,
        "block": 123_456,
        "participant_count": 17,
        "validator_count": 5,
    }


def _claimed_task(tmp_path, plan, *, role=Role.VALIDATOR):
    scheduler = FactoryScheduler(tmp_path / "factory" / "scheduler.sqlite3")
    scheduler.enqueue(
        role=role,
        action=ActionKind.READ_SUBNET_STATE,
        input_commitment=plan.request_sha256(),
        output_scope=MemoryScope.ROLE_PRIVATE,
        output_artifact=ArtifactClass.PRIVATE_OPERATION,
    )
    task = scheduler.claim_next(role, lease_seconds=300)
    assert task is not None
    return scheduler, task


def test_read_only_adapter_binds_snapshot_to_role_task_and_keeps_only_digest(tmp_path):
    plan = _plan()
    snapshot = _snapshot(plan)
    scheduler, task = _claimed_task(tmp_path, plan)
    source = _Source(snapshot)
    adapter = ReadOnlySubnetStateAdapter(scheduler, source=source)

    receipt = adapter.execute(task, plan)

    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert source.calls == [plan]
    assert receipt.output_commitment == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert scheduler.status_counts()[TaskStatus.SUCCEEDED] == 1
    row = sqlite3.connect(scheduler.database_path).execute(
        "SELECT input_commitment, output_commitment, failure_code FROM factory_tasks WHERE id=?", (task.id,)
    ).fetchone()
    assert row == (plan.request_sha256(), receipt.output_commitment, None)
    assert canonical not in str(row)
    scheduler.close()


def test_read_only_adapter_rejects_changed_request_before_calling_source(tmp_path):
    plan = _plan()
    changed_plan = _plan(netuid=43)
    scheduler, task = _claimed_task(tmp_path, plan, role=Role.MINER_QA)
    source = _Source(_snapshot(changed_plan))
    adapter = ReadOnlySubnetStateAdapter(scheduler, source=source)

    with pytest.raises(SubnetStateError, match="does not match task commitment"):
        adapter.execute(task, changed_plan)

    assert source.calls == []
    assert scheduler.status_counts()[TaskStatus.FAILED] == 1
    scheduler.close()


def test_read_only_adapter_rejects_unprojected_identity_data_without_persisting_it(tmp_path):
    plan = _plan()
    scheduler, task = _claimed_task(tmp_path, plan, role=Role.PRODUCT)
    snapshot = _snapshot(plan)
    snapshot["hotkey"] = "forbidden-identity-marker"
    source = _Source(snapshot)
    adapter = ReadOnlySubnetStateAdapter(scheduler, source=source)

    with pytest.raises(SubnetStateError, match="snapshot failed"):
        adapter.execute(task, plan)

    assert source.calls == [plan]
    row = sqlite3.connect(scheduler.database_path).execute(
        "SELECT output_commitment, failure_code FROM factory_tasks WHERE id=?", (task.id,)
    ).fetchone()
    assert row == (None, "subnet-read-failed")
    assert "forbidden-identity-marker" not in str(row)
    scheduler.close()
