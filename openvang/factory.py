"""Explicit authority and memory policy for the OpenVang subnet-agent factory.

The factory is a coordination layer for multiple specialist agents.  It is not
a privileged owner key, a Bittensor signer, or a GitHub automation client.
Every owner-level effect is represented only as an immutable intent and is
denied automatic execution by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class FactoryPolicyError(ValueError):
    """A role, capability, artifact, or intent violates the factory contract."""


class Role(str, Enum):
    """Specialist roles operated within a single subnet's owner workflow."""

    VALIDATOR = "validator"
    MAINTAINER = "maintainer"
    MINER_QA = "miner-qa"
    BUILDER = "builder"
    PRODUCT = "product"
    QA = "qa"
    SCHEDULER = "scheduler"
    SECURITY_QA = "security-qa"


class ActionKind(str, Enum):
    """Actions a role may prepare or perform in the non-privileged factory."""

    READ_SUBNET_STATE = "read-subnet-state"
    READ_REPOSITORY = "read-repository"
    PLAN = "plan"
    RUN_ISOLATED = "run-isolated"
    VALIDATE = "validate"
    SCORE = "score"
    VERIFY_RECEIPT = "verify-receipt"
    WRITE_PRIVATE_MEMORY = "write-private-memory"
    READ_ROLE_MEMORY = "read-role-memory"
    DISPATCH = "dispatch"
    PROPOSE_OWNER_ACTION = "propose-owner-action"
    GITHUB_WRITE = "github-write"
    ONCHAIN_TRANSACTION = "onchain-transaction"
    WALLET_ACCESS = "wallet-access"
    EMISSION_CHANGE = "emission-change"
    GOVERNANCE_VOTE = "governance-vote"
    PUBLICATION = "publication"


class MemoryScope(str, Enum):
    """Visibility classes for a role's memory projection."""

    ROLE_PRIVATE = "role-private"
    SHARED_COMMITMENT = "shared-commitment"
    PUBLISHABLE_COMMITMENT = "publishable-commitment"


class ArtifactClass(str, Enum):
    """Classes with deliberately different publication and retention rules."""

    PRIVATE_REVIEW = "private-review"
    PRIVATE_OPERATION = "private-operation"
    SHARED_COMMITMENT = "shared-commitment"
    PUBLIC_COMMITMENT = "public-commitment"
    PUBLIC_STATUS = "public-status"


_AUTOMATIC_ACTIONS = frozenset(
    {
        ActionKind.READ_SUBNET_STATE,
        ActionKind.READ_REPOSITORY,
        ActionKind.PLAN,
        ActionKind.RUN_ISOLATED,
        ActionKind.VALIDATE,
        ActionKind.SCORE,
        ActionKind.VERIFY_RECEIPT,
        ActionKind.WRITE_PRIVATE_MEMORY,
        ActionKind.READ_ROLE_MEMORY,
        ActionKind.DISPATCH,
        ActionKind.PROPOSE_OWNER_ACTION,
    }
)
_OWNER_ACTIONS = frozenset(
    {
        ActionKind.GITHUB_WRITE,
        ActionKind.ONCHAIN_TRANSACTION,
        ActionKind.WALLET_ACCESS,
        ActionKind.EMISSION_CHANGE,
        ActionKind.GOVERNANCE_VOTE,
        ActionKind.PUBLICATION,
    }
)
_PUBLIC_ARTIFACTS = frozenset({ArtifactClass.PUBLIC_COMMITMENT, ArtifactClass.PUBLIC_STATUS})


@dataclass(frozen=True)
class RoleContract:
    """The minimum authority granted to a specialist role.

    The granted action set must contain only non-privileged capabilities.  A
    role can request an owner action through a commitment-only intent, but it
    cannot obtain a direct effect permission from the registry.
    """

    role: Role
    purpose: str
    actions: frozenset[ActionKind]
    readable_memory: frozenset[MemoryScope]
    writable_memory: frozenset[MemoryScope]

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise FactoryPolicyError("role contract role must be a Role")
        if not self.purpose.strip():
            raise FactoryPolicyError("role purpose must be non-empty")
        if any(not isinstance(action, ActionKind) for action in self.actions):
            raise FactoryPolicyError("role contract actions must be ActionKind values")
        if any(not isinstance(scope, MemoryScope) for scope in self.readable_memory | self.writable_memory):
            raise FactoryPolicyError("role contract memory scopes must be MemoryScope values")
        if not self.actions <= _AUTOMATIC_ACTIONS:
            raise FactoryPolicyError("role contracts cannot grant owner-level effects")
        if not self.readable_memory or not self.writable_memory:
            raise FactoryPolicyError("role contracts need explicit memory scopes")
        if not self.writable_memory <= self.readable_memory:
            raise FactoryPolicyError("a role may write only memory it can read")
        if MemoryScope.PUBLISHABLE_COMMITMENT in self.writable_memory and self.role != Role.VALIDATOR:
            raise FactoryPolicyError("only the validator may write publishable commitments")


@dataclass(frozen=True)
class ActionIntent:
    """A non-executable, commitment-bound request for a protected owner effect."""

    requested_by: Role
    action: ActionKind
    payload_commitment: str
    reason_commitment: str

    def __post_init__(self) -> None:
        if not isinstance(self.requested_by, Role) or not isinstance(self.action, ActionKind):
            raise FactoryPolicyError("action intent role and action must use factory enums")
        if self.action not in _OWNER_ACTIONS:
            raise FactoryPolicyError("an action intent must request an owner-level effect")
        for name, value in (
            ("payload_commitment", self.payload_commitment),
            ("reason_commitment", self.reason_commitment),
        ):
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise FactoryPolicyError(f"{name} must be a lowercase SHA-256 commitment")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "requested_by": self.requested_by.value,
                "action": self.action.value,
                "payload_commitment": self.payload_commitment,
                "reason_commitment": self.reason_commitment,
            }
        )


def _digest(value: Mapping[str, str]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _contract(
    role: Role,
    purpose: str,
    actions: Iterable[ActionKind],
    readable_memory: Iterable[MemoryScope],
    writable_memory: Iterable[MemoryScope],
) -> RoleContract:
    return RoleContract(
        role=role,
        purpose=purpose,
        actions=frozenset(actions),
        readable_memory=frozenset(readable_memory),
        writable_memory=frozenset(writable_memory),
    )


def default_contracts() -> tuple[RoleContract, ...]:
    """Return the fixed, least-privilege contracts for the initial factory."""
    private = (MemoryScope.ROLE_PRIVATE, MemoryScope.SHARED_COMMITMENT)
    return (
        _contract(
            Role.VALIDATOR,
            "Validate subnet work, score permitted artifacts, and verify receipt-safe evidence.",
            (
                ActionKind.READ_SUBNET_STATE,
                ActionKind.VALIDATE,
                ActionKind.SCORE,
                ActionKind.VERIFY_RECEIPT,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            (*private, MemoryScope.PUBLISHABLE_COMMITMENT),
            (*private, MemoryScope.PUBLISHABLE_COMMITMENT),
        ),
        _contract(
            Role.MAINTAINER,
            "Prepare repository stewardship analysis and private maintainer recommendations.",
            (
                ActionKind.READ_REPOSITORY,
                ActionKind.PLAN,
                ActionKind.VALIDATE,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
        _contract(
            Role.MINER_QA,
            "Exercise miner-facing behavior and verify protocol and output conformance.",
            (
                ActionKind.READ_SUBNET_STATE,
                ActionKind.RUN_ISOLATED,
                ActionKind.VALIDATE,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
        _contract(
            Role.BUILDER,
            "Build and run bounded workloads in an isolated execution environment.",
            (
                ActionKind.READ_REPOSITORY,
                ActionKind.RUN_ISOLATED,
                ActionKind.VALIDATE,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
        _contract(
            Role.PRODUCT,
            "Synthesize public product signals into plans and owner-reviewable proposals.",
            (
                ActionKind.READ_SUBNET_STATE,
                ActionKind.READ_REPOSITORY,
                ActionKind.PLAN,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
        _contract(
            Role.QA,
            "Run independent acceptance, regression, and integration checks.",
            (
                ActionKind.READ_REPOSITORY,
                ActionKind.RUN_ISOLATED,
                ActionKind.VALIDATE,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
        _contract(
            Role.SCHEDULER,
            "Dispatch bounded work and recover queue leases without receiving owner authority.",
            (
                ActionKind.DISPATCH,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.WRITE_PRIVATE_MEMORY,
            ),
            private,
            private,
        ),
        _contract(
            Role.SECURITY_QA,
            "Perform defensive adversarial QA and propose containment or remediation.",
            (
                ActionKind.READ_REPOSITORY,
                ActionKind.RUN_ISOLATED,
                ActionKind.VALIDATE,
                ActionKind.WRITE_PRIVATE_MEMORY,
                ActionKind.READ_ROLE_MEMORY,
                ActionKind.PROPOSE_OWNER_ACTION,
            ),
            private,
            private,
        ),
    )


class FactoryPolicy:
    """Validate actions, memory exchange, and publication before adapters exist."""

    def __init__(self, contracts: Iterable[RoleContract] | None = None):
        selected = tuple(default_contracts() if contracts is None else contracts)
        if set(contract.role for contract in selected) != set(Role):
            raise FactoryPolicyError("factory policy must define every role exactly once")
        if len({contract.role for contract in selected}) != len(selected):
            raise FactoryPolicyError("factory policy defines a role more than once")
        self._contracts = {contract.role: contract for contract in selected}

    @property
    def contracts(self) -> tuple[RoleContract, ...]:
        return tuple(self._contracts[role] for role in Role)

    def contract(self, role: Role) -> RoleContract:
        return self._contracts[Role(role)]

    def allows(self, role: Role, action: ActionKind) -> bool:
        """Return whether a non-owner action is granted to this role."""
        return ActionKind(action) in self.contract(Role(role)).actions

    def assert_allowed(self, role: Role, action: ActionKind) -> None:
        if not self.allows(role, action):
            raise FactoryPolicyError(f"{Role(role).value} cannot perform {ActionKind(action).value}")

    def can_read_memory(self, role: Role, scope: MemoryScope) -> bool:
        return MemoryScope(scope) in self.contract(Role(role)).readable_memory

    def can_write_memory(self, role: Role, scope: MemoryScope) -> bool:
        return MemoryScope(scope) in self.contract(Role(role)).writable_memory

    def can_transfer_memory(
        self,
        *,
        source: Role,
        target: Role,
        scope: MemoryScope,
        artifact: ArtifactClass,
    ) -> bool:
        """Allow only commitment-level sharing between different roles.

        A role-private item—including private maintainer review evidence—never
        crosses a role boundary through the factory.  Cross-role collaboration
        uses a shaped commitment, not raw history, prompts, or reviewer output.
        """
        source = Role(source)
        target = Role(target)
        scope = MemoryScope(scope)
        artifact = ArtifactClass(artifact)
        if not self.can_read_memory(source, scope) or not self.can_read_memory(target, scope):
            return False
        if source == target:
            return True
        return scope in {MemoryScope.SHARED_COMMITMENT, MemoryScope.PUBLISHABLE_COMMITMENT} and artifact in {
            ArtifactClass.SHARED_COMMITMENT,
            ArtifactClass.PUBLIC_COMMITMENT,
        }

    def may_publish(self, role: Role, artifact: ArtifactClass) -> bool:
        """Publication is never a role capability in the initial factory."""
        Role(role)
        ArtifactClass(artifact)
        return False

    def public_contract(self) -> dict[str, object]:
        """Return static policy metadata safe for an operator or deployment check.

        This is a registry description, not runtime telemetry: it contains no
        assigned work, private memory, artifact, review, wallet, or owner data.
        """
        return {
            "schema_version": 1,
            "roles": [
                {
                    "role": contract.role.value,
                    "actions": sorted(action.value for action in contract.actions),
                    "readable_memory": sorted(scope.value for scope in contract.readable_memory),
                    "writable_memory": sorted(scope.value for scope in contract.writable_memory),
                }
                for contract in self.contracts
            ],
            "owner_actions_require_external_approval": sorted(action.value for action in _OWNER_ACTIONS),
            "automatic_owner_execution": False,
            "automatic_publication": False,
        }

    def public_shape_allowed(self, artifact: ArtifactClass, fields: Iterable[str]) -> bool:
        """Validate the narrow class of commitment-only public artifacts.

        This rejects private-review output by construction and keeps public
        evidence independent of agent prompts, memory, histories, or reasoning.
        """
        artifact = ArtifactClass(artifact)
        field_set = frozenset(fields)
        if artifact not in _PUBLIC_ARTIFACTS:
            return False
        allowed = {
            "schema_version",
            "policy_version",
            "commitment",
            "status",
            "verified_at",
        }
        return bool(field_set) and field_set <= allowed

    def intent(self, role: Role, action: ActionKind, *, payload: Mapping[str, object], reason: str) -> ActionIntent:
        """Prepare an owner-reviewable request without retaining executable payload text."""
        role = Role(role)
        action = ActionKind(action)
        self.assert_allowed(role, ActionKind.PROPOSE_OWNER_ACTION)
        if action not in _OWNER_ACTIONS:
            raise FactoryPolicyError("factory intents are reserved for owner-level actions")
        if not isinstance(reason, str) or not reason.strip():
            raise FactoryPolicyError("owner-action reason must be non-empty")
        try:
            payload_commitment = _digest({"payload": json.dumps(payload, sort_keys=True, separators=(",", ":"))})
        except (TypeError, ValueError) as exc:
            raise FactoryPolicyError("owner-action payload must be JSON-compatible") from exc
        return ActionIntent(
            requested_by=role,
            action=action,
            payload_commitment=payload_commitment,
            reason_commitment=hashlib.sha256(reason.strip().encode("utf-8")).hexdigest(),
        )

    def can_auto_execute(self, intent: ActionIntent) -> bool:
        """Owner effects cannot be auto-executed by factory policy, ever."""
        if not isinstance(intent, ActionIntent):
            raise FactoryPolicyError("execution requires an action intent")
        return False
