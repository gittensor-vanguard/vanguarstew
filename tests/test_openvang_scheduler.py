import sqlite3
import stat

import pytest

from openvang.factory import ActionKind, ArtifactClass, MemoryScope, Role
from openvang.scheduler import FactoryScheduler, SchedulerError, TaskStatus


def _digest(letter):
    return letter * 64


def _scheduler(tmp_path, *, budget=4):
    return FactoryScheduler(tmp_path / "factory" / "scheduler.sqlite3", max_active_budget=budget)


def test_scheduler_dispatches_only_to_the_target_role_and_keeps_commitments(tmp_path):
    with _scheduler(tmp_path) as scheduler:
        assert scheduler.enqueue(
            role=Role.MAINTAINER,
            action=ActionKind.VALIDATE,
            input_commitment=_digest("a"),
            output_scope=MemoryScope.ROLE_PRIVATE,
            output_artifact=ArtifactClass.PRIVATE_REVIEW,
            budget_units=2,
        )
        assert scheduler.claim_next(Role.VALIDATOR) is None

        task = scheduler.claim_next(Role.MAINTAINER)
        assert task is not None
        assert task.input_commitment == _digest("a")
        assert task.output_artifact == ArtifactClass.PRIVATE_REVIEW
        with pytest.raises(SchedulerError, match="not running for this role"):
            scheduler.complete(task.id, role=Role.QA, output_commitment=_digest("b"))
        scheduler.complete(task.id, role=Role.MAINTAINER, output_commitment=_digest("b"))

        assert scheduler.status_counts()[TaskStatus.SUCCEEDED] == 1
        columns = {
            row[1]
            for row in sqlite3.connect(scheduler.database_path).execute("PRAGMA table_info(factory_tasks)")
        }
        assert "payload" not in columns
        assert "output" not in columns


def test_scheduler_rejects_owner_effects_and_invalid_output_boundaries(tmp_path):
    with _scheduler(tmp_path) as scheduler:
        with pytest.raises(SchedulerError, match="not permitted"):
            scheduler.enqueue(
                role=Role.VALIDATOR,
                action=ActionKind.ONCHAIN_TRANSACTION,
                input_commitment=_digest("a"),
                output_scope=MemoryScope.PUBLISHABLE_COMMITMENT,
                output_artifact=ArtifactClass.PUBLIC_COMMITMENT,
            )
        with pytest.raises(SchedulerError, match="output scope or artifact"):
            scheduler.enqueue(
                role=Role.MAINTAINER,
                action=ActionKind.VALIDATE,
                input_commitment=_digest("b"),
                output_scope=MemoryScope.SHARED_COMMITMENT,
                output_artifact=ArtifactClass.PRIVATE_REVIEW,
            )
        with pytest.raises(SchedulerError, match="not schedulable"):
            scheduler.enqueue(
                role=Role.MAINTAINER,
                action=ActionKind.PROPOSE_OWNER_ACTION,
                input_commitment=_digest("c"),
                output_scope=MemoryScope.ROLE_PRIVATE,
                output_artifact=ArtifactClass.PRIVATE_REVIEW,
            )


def test_scheduler_enforces_active_budget_and_deduplicates_input_commitments(tmp_path):
    with _scheduler(tmp_path, budget=2) as scheduler:
        kwargs = {
            "role": Role.BUILDER,
            "action": ActionKind.RUN_ISOLATED,
            "input_commitment": _digest("a"),
            "output_scope": MemoryScope.ROLE_PRIVATE,
            "output_artifact": ArtifactClass.PRIVATE_OPERATION,
            "budget_units": 2,
        }
        assert scheduler.enqueue(**kwargs)
        assert not scheduler.enqueue(**kwargs)
        with pytest.raises(SchedulerError, match="active budget"):
            scheduler.enqueue(
                role=Role.QA,
                action=ActionKind.RUN_ISOLATED,
                input_commitment=_digest("b"),
                output_scope=MemoryScope.ROLE_PRIVATE,
                output_artifact=ArtifactClass.PRIVATE_OPERATION,
            )

        task = scheduler.claim_next(Role.BUILDER)
        scheduler.complete(task.id, role=Role.BUILDER, output_commitment=_digest("c"))
        assert scheduler.active_budget() == 0
        assert scheduler.enqueue(
            role=Role.QA,
            action=ActionKind.RUN_ISOLATED,
            input_commitment=_digest("b"),
            output_scope=MemoryScope.ROLE_PRIVATE,
            output_artifact=ArtifactClass.PRIVATE_OPERATION,
        )


def test_scheduler_recovers_expired_lease_and_keeps_storage_owner_only(tmp_path):
    with _scheduler(tmp_path) as scheduler:
        assert scheduler.enqueue(
            role=Role.SECURITY_QA,
            action=ActionKind.RUN_ISOLATED,
            input_commitment=_digest("a"),
            output_scope=MemoryScope.ROLE_PRIVATE,
            output_artifact=ArtifactClass.PRIVATE_OPERATION,
        )
        first = scheduler.claim_next(Role.SECURITY_QA, lease_seconds=300)
        scheduler._connection.execute(
            "UPDATE factory_tasks SET lease_until=? WHERE id=?", ("2000-01-01T00:00:00+00:00", first.id)
        )

        second = scheduler.claim_next(Role.SECURITY_QA)
        assert second is not None
        assert second.id == first.id
        assert second.attempts == 2
        assert stat.S_IMODE(scheduler.database_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(scheduler.database_path.parent.stat().st_mode) == 0o700


def test_only_validator_can_schedule_a_staged_public_commitment(tmp_path):
    with _scheduler(tmp_path) as scheduler:
        assert scheduler.enqueue(
            role=Role.VALIDATOR,
            action=ActionKind.VERIFY_RECEIPT,
            input_commitment=_digest("a"),
            output_scope=MemoryScope.PUBLISHABLE_COMMITMENT,
            output_artifact=ArtifactClass.PUBLIC_COMMITMENT,
        )
        with pytest.raises(SchedulerError, match="output scope or artifact"):
            scheduler.enqueue(
                role=Role.QA,
                action=ActionKind.VALIDATE,
                input_commitment=_digest("b"),
                output_scope=MemoryScope.PUBLISHABLE_COMMITMENT,
                output_artifact=ArtifactClass.PUBLIC_COMMITMENT,
            )
