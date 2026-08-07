"""Approval-bound adapter for isolated OpenVang build and QA work.

This module deliberately connects the factory only to the existing sealed
executor.  It is not a shell runner, remote-execution client, credential
bridge, or publication mechanism.  A task may run only when its factory
commitment exactly equals an owner-approved ``SealedExecutionPlan`` request.
The scheduler retains a digest of the verified aggregate envelope, never the
envelope, workload, private output, or error detail itself.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from benchmark.sealed_aggregate import verify_sealed_aggregate
from benchmark.sealed_execution import SealedExecutionPlan, SealedExecutor

from .factory import ActionKind, ArtifactClass, MemoryScope, Role
from .scheduler import FactoryScheduler, FactoryTask, SchedulerError


class IsolatedExecutionError(RuntimeError):
    """An isolated task was not authorized, failed, or produced no safe receipt."""


_ISOLATED_ROLES = frozenset({Role.MINER_QA, Role.BUILDER, Role.QA, Role.SECURITY_QA})
_SHA256_LENGTH = 64


@dataclass(frozen=True)
class IsolatedExecutionReceipt:
    """Commitment-only outcome for a locally completed sealed workload."""

    task_id: int
    input_commitment: str
    output_commitment: str


def _matches_commitment(value: object, expected: str) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
        and hmac.compare_digest(value, expected)
    )


class IsolatedExecutionAdapter:
    """Execute one live leased build/QA task through ``SealedExecutor`` only.

    The caller must first queue a permitted ``run-isolated`` task whose input
    commitment is the plan's ``request_sha256()``, then claim it using the same
    role.  The separate approval argument has to match that exact commitment;
    neither scheduler state nor a role can self-approve a changed plan.
    """

    def __init__(self, scheduler: FactoryScheduler, *, executor: SealedExecutor | None = None):
        if not isinstance(scheduler, FactoryScheduler):
            raise TypeError("scheduler must be a FactoryScheduler")
        if executor is not None and not isinstance(executor, SealedExecutor):
            raise TypeError("executor must be a SealedExecutor")
        self.scheduler = scheduler
        self.executor = executor or SealedExecutor()

    def execute(
        self,
        task: FactoryTask,
        plan: SealedExecutionPlan,
        *,
        approved_request_sha256: str,
    ) -> IsolatedExecutionReceipt:
        """Run one approved plan and store its aggregate digest as task output.

        No sealed result is returned to the caller.  A pre-execution policy or
        binding failure marks a verified claimed task failed without invoking
        the executor.  Executor and aggregate-gate failures also retain only a
        fixed failure code, never a private exception or workload transcript.
        """
        try:
            task = self.scheduler.require_running(task)
        except SchedulerError as exc:
            raise IsolatedExecutionError("isolated task is not an active claimed task") from exc

        try:
            self._validate_binding(task, plan, approved_request_sha256)
        except IsolatedExecutionError:
            self._fail(task, code="isolated-approval-rejected")
            raise

        try:
            envelope = self.executor.execute_approved(
                plan,
                approved_request_sha256=approved_request_sha256,
            )
            if not isinstance(envelope, str) or not verify_sealed_aggregate(
                envelope,
                expected_challenge=plan.challenge,
            ).get("ok"):
                raise ValueError("sealed aggregate rejected")
            output_commitment = hashlib.sha256(envelope.encode("utf-8")).hexdigest()
        except Exception:
            self._fail(task, code="sealed-execution-failed")
            raise IsolatedExecutionError("sealed execution failed") from None

        try:
            self.scheduler.complete(
                task.id,
                role=task.role,
                output_commitment=output_commitment,
            )
        except SchedulerError as exc:
            raise IsolatedExecutionError("sealed result could not be recorded") from exc
        return IsolatedExecutionReceipt(
            task_id=task.id,
            input_commitment=task.input_commitment,
            output_commitment=output_commitment,
        )

    @staticmethod
    def _validate_binding(
        task: FactoryTask,
        plan: SealedExecutionPlan,
        approved_request_sha256: str,
    ) -> None:
        if task.role not in _ISOLATED_ROLES or task.action != ActionKind.RUN_ISOLATED:
            raise IsolatedExecutionError("task is not authorized for isolated execution")
        if (
            task.output_scope != MemoryScope.ROLE_PRIVATE
            or task.output_artifact != ArtifactClass.PRIVATE_OPERATION
        ):
            raise IsolatedExecutionError("isolated task output is not role-private")
        if not isinstance(plan, SealedExecutionPlan):
            raise IsolatedExecutionError("an exact sealed execution plan is required")
        request_commitment = plan.request_sha256()
        if not hmac.compare_digest(task.input_commitment, request_commitment):
            raise IsolatedExecutionError("sealed plan does not match task commitment")
        if not _matches_commitment(approved_request_sha256, request_commitment):
            raise IsolatedExecutionError("sealed plan does not have exact external approval")

    def _fail(self, task: FactoryTask, *, code: str) -> None:
        try:
            self.scheduler.fail(task.id, role=task.role, code=code)
        except SchedulerError:
            # Never replace a useful authorization/execution error with a task
            # state detail. The scheduler contains no raw result either way.
            pass
