"""Private, role-aware task scheduler for the OpenVang factory.

The scheduler coordinates *commitments*, not raw prompts, repository data,
credentials, review evidence, or executable owner-action payloads. It does not
run a worker itself and cannot call Bittensor, a wallet, GitHub, or a public
endpoint. A worker must claim only tasks assigned to its own factory role.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .factory import ActionKind, ArtifactClass, FactoryPolicy, MemoryScope, Role


class SchedulerError(ValueError):
    """The requested task lifecycle operation violates the scheduler contract."""


class TaskStatus(str):
    """Stored task states. Kept as strings for portable SQLite inspection."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEFERRED = "deferred"
    FAILED = "failed"


_ACTIVE_STATUSES = (TaskStatus.QUEUED, TaskStatus.RUNNING)
_TERMINAL_STATUSES = (TaskStatus.SUCCEEDED, TaskStatus.DEFERRED, TaskStatus.FAILED)
_VALID_STATUSES = (*_ACTIVE_STATUSES, *_TERMINAL_STATUSES)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


def _commitment(value: object, *, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SchedulerError(f"{field} must be a lowercase SHA-256 commitment")
    return value


def _positive_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SchedulerError(f"{field} must be a positive integer")
    return value


def _output_allowed(
    policy: FactoryPolicy,
    *,
    role: Role,
    scope: MemoryScope,
    artifact: ArtifactClass,
) -> bool:
    """Require output scope and artifact classification to agree exactly."""
    if not policy.can_write_memory(role, scope):
        return False
    if artifact == ArtifactClass.PRIVATE_REVIEW:
        return role == Role.MAINTAINER and scope == MemoryScope.ROLE_PRIVATE
    if artifact == ArtifactClass.PRIVATE_OPERATION:
        return scope == MemoryScope.ROLE_PRIVATE
    if artifact == ArtifactClass.SHARED_COMMITMENT:
        return scope == MemoryScope.SHARED_COMMITMENT
    if artifact == ArtifactClass.PUBLIC_COMMITMENT:
        return role == Role.VALIDATOR and scope == MemoryScope.PUBLISHABLE_COMMITMENT
    # Public status is a publication act, so no scheduler task may create it.
    return False


@dataclass(frozen=True)
class FactoryTask:
    """A safe task projection: all workload and result content is commitment-only."""

    id: int
    role: Role
    action: ActionKind
    input_commitment: str
    output_scope: MemoryScope
    output_artifact: ArtifactClass
    budget_units: int
    attempts: int


class FactoryScheduler:
    """Durable, bounded scheduler for non-privileged factory work.

    `max_active_budget` limits the combined units of queued and running tasks.
    It provides a deterministic local spending/throughput guard before an
    external worker adapter exists; it is not a wallet or on-chain accounting
    mechanism.
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        policy: FactoryPolicy | None = None,
        max_active_budget: int = 10,
    ):
        self.policy = policy or FactoryPolicy()
        self.database_path = Path(database_path)
        self.max_active_budget = _positive_integer(max_active_budget, field="max_active_budget")
        _secure_directory(self.database_path.parent)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._initialize()
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS factory_tasks (
                    id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    input_commitment TEXT NOT NULL UNIQUE,
                    output_scope TEXT NOT NULL,
                    output_artifact TEXT NOT NULL,
                    budget_units INTEGER NOT NULL CHECK (budget_units > 0),
                    status TEXT NOT NULL CHECK (status IN
                        ('queued', 'running', 'succeeded', 'deferred', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_until TEXT,
                    output_commitment TEXT,
                    failure_code TEXT
                );
                CREATE INDEX IF NOT EXISTS factory_tasks_dispatch
                    ON factory_tasks(role, status, created_at, id);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "FactoryScheduler":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def active_budget(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COALESCE(SUM(budget_units), 0) AS total FROM factory_tasks "
                "WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["total"])

    def enqueue(
        self,
        *,
        role: Role,
        action: ActionKind,
        input_commitment: str,
        output_scope: MemoryScope,
        output_artifact: ArtifactClass,
        budget_units: int = 1,
    ) -> bool:
        """Queue a permitted role task once, respecting the active budget cap."""
        scheduler_role = Role.SCHEDULER
        self.policy.assert_allowed(scheduler_role, ActionKind.DISPATCH)
        role = Role(role)
        action = ActionKind(action)
        output_scope = MemoryScope(output_scope)
        output_artifact = ArtifactClass(output_artifact)
        input_commitment = _commitment(input_commitment, field="input_commitment")
        budget_units = _positive_integer(budget_units, field="budget_units")
        if not self.policy.allows(role, action):
            raise SchedulerError(f"{role.value} is not permitted to perform {action.value}")
        if action == ActionKind.PROPOSE_OWNER_ACTION:
            raise SchedulerError("owner-action proposals are not schedulable worker tasks")
        if not _output_allowed(
            self.policy,
            role=role,
            scope=output_scope,
            artifact=output_artifact,
        ):
            raise SchedulerError("task output scope or artifact is not permitted for this role")
        now = _utcnow()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                duplicate = self._connection.execute(
                    "SELECT 1 FROM factory_tasks WHERE input_commitment=?", (input_commitment,)
                ).fetchone()
                if duplicate is not None:
                    self._connection.execute("COMMIT")
                    return False
                if self.active_budget() + budget_units > self.max_active_budget:
                    raise SchedulerError("active budget limit would be exceeded")
                self._connection.execute(
                    """
                    INSERT INTO factory_tasks(
                        role, action, input_commitment, output_scope, output_artifact,
                        budget_units, status, attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
                    """,
                    (
                        role.value,
                        action.value,
                        input_commitment,
                        output_scope.value,
                        output_artifact.value,
                        budget_units,
                        now,
                        now,
                    ),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        return True

    def recover_expired_leases(self) -> int:
        """Make work recoverable after an interrupted worker lease expires."""
        now = _utcnow()
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE factory_tasks
                SET status='queued', lease_until=NULL, failure_code='lease-expired', updated_at=?
                WHERE status='running' AND lease_until IS NOT NULL AND lease_until <= ?
                """,
                (now, now),
            )
        return cursor.rowcount

    def claim_next(self, role: Role, *, lease_seconds: int = 300) -> FactoryTask | None:
        """Claim one queued task for exactly the worker's declared role."""
        role = Role(role)
        lease_seconds = _positive_integer(lease_seconds, field="lease_seconds")
        self.recover_expired_leases()
        now = _utcnow()
        lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).replace(
            microsecond=0
        ).isoformat()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT id, role, action, input_commitment, output_scope, output_artifact,
                           budget_units, attempts
                    FROM factory_tasks
                    WHERE role=? AND status='queued'
                    ORDER BY created_at, id LIMIT 1
                    """,
                    (role.value,),
                ).fetchone()
                if row is None:
                    self._connection.execute("COMMIT")
                    return None
                cursor = self._connection.execute(
                    """
                    UPDATE factory_tasks
                    SET status='running', attempts=attempts+1, lease_until=?, updated_at=?
                    WHERE id=? AND status='queued'
                    """,
                    (lease_until, now, row["id"]),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        if cursor.rowcount != 1:
            return None
        return _task_from_row(row, attempts=int(row["attempts"]) + 1)

    def require_running(self, task: FactoryTask) -> FactoryTask:
        """Return the canonical task only while its matching worker lease is live.

        Adapters call this immediately before an irreversible local operation.
        It prevents a hand-built or stale ``FactoryTask`` projection from being
        used as authority to start work.  This is a scheduler-state check, not
        a credential system: worker identity and process isolation remain the
        responsibility of the adapter deployment.
        """
        if not isinstance(task, FactoryTask):
            raise SchedulerError("a claimed FactoryTask is required")
        now = _utcnow()
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, role, action, input_commitment, output_scope, output_artifact,
                       budget_units, attempts
                FROM factory_tasks
                WHERE id=? AND role=? AND status='running'
                  AND lease_until IS NOT NULL AND lease_until > ?
                """,
                (task.id, task.role.value, now),
            ).fetchone()
        if row is None:
            raise SchedulerError("task is not running with a live lease for this role")
        current = _task_from_row(row, attempts=int(row["attempts"]))
        if current != task:
            raise SchedulerError("claimed task does not match the scheduler record")
        return current

    def complete(self, task_id: int, *, role: Role, output_commitment: str) -> None:
        """Finish a claimed task with a result digest only."""
        self._transition(
            task_id,
            role=role,
            status=TaskStatus.SUCCEEDED,
            output_commitment=_commitment(output_commitment, field="output_commitment"),
        )

    def defer(self, task_id: int, *, role: Role, code: str) -> None:
        self._transition(task_id, role=role, status=TaskStatus.DEFERRED, failure_code=_code(code))

    def fail(self, task_id: int, *, role: Role, code: str) -> None:
        self._transition(task_id, role=role, status=TaskStatus.FAILED, failure_code=_code(code))

    def _transition(
        self,
        task_id: int,
        *,
        role: Role,
        status: str,
        output_commitment: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        if isinstance(task_id, bool) or not isinstance(task_id, int) or task_id < 1:
            raise SchedulerError("task_id must be a positive integer")
        role = Role(role)
        if status not in _TERMINAL_STATUSES:
            raise SchedulerError("scheduler transition must be terminal")
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE factory_tasks
                SET status=?, output_commitment=?, failure_code=?, lease_until=NULL, updated_at=?
                WHERE id=? AND role=? AND status='running'
                """,
                (status, output_commitment, failure_code, _utcnow(), task_id, role.value),
            )
        if cursor.rowcount != 1:
            raise SchedulerError("task is not running for this role")

    def status_counts(self) -> dict[str, int]:
        """Return aggregate local counts without task, repository, or output data."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS total FROM factory_tasks GROUP BY status"
            ).fetchall()
        counts = {status: 0 for status in _VALID_STATUSES}
        counts.update({str(row["status"]): int(row["total"]) for row in rows})
        return counts


def _code(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 80:
        raise SchedulerError("failure code must be a non-empty string of at most 80 characters")
    if any(char.isspace() for char in value):
        raise SchedulerError("failure code must not contain whitespace")
    return value


def _task_from_row(row: sqlite3.Row, *, attempts: int) -> FactoryTask:
    try:
        return FactoryTask(
            id=int(row["id"]),
            role=Role(row["role"]),
            action=ActionKind(row["action"]),
            input_commitment=str(row["input_commitment"]),
            output_scope=MemoryScope(row["output_scope"]),
            output_artifact=ArtifactClass(row["output_artifact"]),
            budget_units=int(row["budget_units"]),
            attempts=attempts,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SchedulerError("stored task violated the factory contract") from exc
