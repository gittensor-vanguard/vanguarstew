"""Commitment-only adapter contract for read-only OpenVang subnet snapshots.

The factory intentionally does not ship a Bittensor client, wallet, endpoint,
or credential.  An operator may inject a separately reviewed read-only source.
This adapter binds its request to a leased scheduler task, validates a narrow
identity-free snapshot schema, and retains only its digest in scheduler state.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from .factory import ActionKind, ArtifactClass, MemoryScope, Role
from .scheduler import FactoryScheduler, FactoryTask, SchedulerError


class SubnetStateError(RuntimeError):
    """A subnet state task, source, or snapshot violated the local contract."""


class ReadOnlySubnetStateSource(Protocol):
    """Minimal source interface for a separately deployed read-only collector."""

    def read_snapshot(self, plan: "SubnetStatePlan") -> Mapping[str, object]:
        """Return exactly one ``subnet-state-v1`` shaped snapshot."""


_NETWORK_RE = re.compile(r"[a-z][a-z0-9-]{0,31}")
_READ_ONLY_ROLES = frozenset({Role.VALIDATOR, Role.MINER_QA, Role.PRODUCT})
_SNAPSHOT_KEYS = frozenset(
    {
        "schema_version",
        "network",
        "netuid",
        "block",
        "participant_count",
        "validator_count",
    }
)


def _canonical_json(value: Mapping[str, object]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _bounded_int(value: object, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise SubnetStateError(f"{label} is outside the supported range")
    return value


@dataclass(frozen=True)
class SubnetStatePlan:
    """An exact, non-secret request for one read-only subnet state projection."""

    network: str
    netuid: int

    def __post_init__(self) -> None:
        if not isinstance(self.network, str) or not _NETWORK_RE.fullmatch(self.network):
            raise SubnetStateError("network must be a lowercase network identifier")
        _bounded_int(self.netuid, label="netuid", minimum=0, maximum=2**32 - 1)

    def request_body(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "projection": "subnet-state-v1",
            "network": self.network,
            "netuid": self.netuid,
        }

    def request_sha256(self) -> str:
        return hashlib.sha256(_canonical_json(self.request_body()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SubnetStateReceipt:
    """Commitment-only record of a completed read-only snapshot task."""

    task_id: int
    input_commitment: str
    output_commitment: str


def _normalize_snapshot(snapshot: Mapping[str, object], *, plan: SubnetStatePlan) -> dict[str, object]:
    if not isinstance(snapshot, Mapping) or set(snapshot) != _SNAPSHOT_KEYS:
        raise SubnetStateError("subnet snapshot does not match the fixed projection")
    if snapshot.get("schema_version") != 1:
        raise SubnetStateError("subnet snapshot schema is unsupported")
    network = snapshot.get("network")
    if not isinstance(network, str) or not hmac.compare_digest(network, plan.network):
        raise SubnetStateError("subnet snapshot network does not match its request")
    netuid = _bounded_int(snapshot.get("netuid"), label="netuid", minimum=0, maximum=2**32 - 1)
    if netuid != plan.netuid:
        raise SubnetStateError("subnet snapshot netuid does not match its request")
    block = _bounded_int(snapshot.get("block"), label="block", minimum=0, maximum=2**63 - 1)
    participant_count = _bounded_int(
        snapshot.get("participant_count"),
        label="participant_count",
        minimum=0,
        maximum=1_000_000,
    )
    validator_count = _bounded_int(
        snapshot.get("validator_count"),
        label="validator_count",
        minimum=0,
        maximum=participant_count,
    )
    return {
        "schema_version": 1,
        "network": network,
        "netuid": netuid,
        "block": block,
        "participant_count": participant_count,
        "validator_count": validator_count,
    }


class ReadOnlySubnetStateAdapter:
    """Store a verified digest from one exact read-only subnet state request."""

    def __init__(self, scheduler: FactoryScheduler, *, source: ReadOnlySubnetStateSource):
        if not isinstance(scheduler, FactoryScheduler):
            raise TypeError("scheduler must be a FactoryScheduler")
        if not callable(getattr(source, "read_snapshot", None)):
            raise TypeError("source must provide read_snapshot(plan)")
        self.scheduler = scheduler
        self.source = source

    def execute(self, task: FactoryTask, plan: SubnetStatePlan) -> SubnetStateReceipt:
        """Collect and retain only the canonical snapshot commitment.

        The raw source response is intentionally neither returned nor written
        to scheduler state.  This method makes no endpoint, SDK, signer, or
        credential decision; those stay in the separately deployed source.
        """
        try:
            task = self.scheduler.require_running(task)
        except SchedulerError as exc:
            raise SubnetStateError("subnet task is not an active claimed task") from exc

        try:
            self._validate_binding(task, plan)
        except SubnetStateError:
            self._fail(task, code="subnet-read-rejected")
            raise

        try:
            snapshot = _normalize_snapshot(self.source.read_snapshot(plan), plan=plan)
            output_commitment = hashlib.sha256(_canonical_json(snapshot).encode("utf-8")).hexdigest()
        except Exception:
            self._fail(task, code="subnet-read-failed")
            raise SubnetStateError("read-only subnet snapshot failed") from None

        try:
            self.scheduler.complete(
                task.id,
                role=task.role,
                output_commitment=output_commitment,
            )
        except SchedulerError as exc:
            raise SubnetStateError("subnet snapshot could not be recorded") from exc
        return SubnetStateReceipt(
            task_id=task.id,
            input_commitment=task.input_commitment,
            output_commitment=output_commitment,
        )

    @staticmethod
    def _validate_binding(task: FactoryTask, plan: SubnetStatePlan) -> None:
        if task.role not in _READ_ONLY_ROLES or task.action != ActionKind.READ_SUBNET_STATE:
            raise SubnetStateError("task is not authorized for read-only subnet state")
        if (
            task.output_scope != MemoryScope.ROLE_PRIVATE
            or task.output_artifact != ArtifactClass.PRIVATE_OPERATION
        ):
            raise SubnetStateError("subnet task output is not role-private")
        if not isinstance(plan, SubnetStatePlan):
            raise SubnetStateError("an exact subnet state plan is required")
        if not hmac.compare_digest(task.input_commitment, plan.request_sha256()):
            raise SubnetStateError("subnet state plan does not match task commitment")

    def _fail(self, task: FactoryTask, *, code: str) -> None:
        try:
            self.scheduler.fail(task.id, role=task.role, code=code)
        except SchedulerError:
            pass
