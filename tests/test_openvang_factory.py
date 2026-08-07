import hashlib
import json

import pytest

from openvang.factory import (
    ActionKind,
    ArtifactClass,
    FactoryPolicy,
    FactoryPolicyError,
    MemoryScope,
    Role,
    RoleContract,
)


def test_default_policy_declares_every_role_without_owner_effects():
    policy = FactoryPolicy()

    assert {contract.role for contract in policy.contracts} == set(Role)
    for contract in policy.contracts:
        assert ActionKind.GITHUB_WRITE not in contract.actions
        assert ActionKind.ONCHAIN_TRANSACTION not in contract.actions
        assert ActionKind.WALLET_ACCESS not in contract.actions
        assert ActionKind.EMISSION_CHANGE not in contract.actions
        assert ActionKind.GOVERNANCE_VOTE not in contract.actions
        assert ActionKind.PUBLICATION not in contract.actions


def test_validator_alone_may_write_publishable_commitments():
    policy = FactoryPolicy()

    assert policy.can_write_memory(Role.VALIDATOR, MemoryScope.PUBLISHABLE_COMMITMENT)
    for role in set(Role) - {Role.VALIDATOR}:
        assert not policy.can_write_memory(role, MemoryScope.PUBLISHABLE_COMMITMENT)


def test_role_private_review_cannot_cross_role_boundary_or_be_published():
    policy = FactoryPolicy()

    assert not policy.can_transfer_memory(
        source=Role.MAINTAINER,
        target=Role.VALIDATOR,
        scope=MemoryScope.ROLE_PRIVATE,
        artifact=ArtifactClass.PRIVATE_REVIEW,
    )
    assert not policy.may_publish(Role.MAINTAINER, ArtifactClass.PRIVATE_REVIEW)
    assert not policy.public_shape_allowed(ArtifactClass.PRIVATE_REVIEW, {"commitment"})


def test_only_commitment_level_artifact_can_cross_role_boundary():
    policy = FactoryPolicy()

    assert policy.can_transfer_memory(
        source=Role.QA,
        target=Role.VALIDATOR,
        scope=MemoryScope.SHARED_COMMITMENT,
        artifact=ArtifactClass.SHARED_COMMITMENT,
    )
    assert not policy.can_transfer_memory(
        source=Role.QA,
        target=Role.VALIDATOR,
        scope=MemoryScope.SHARED_COMMITMENT,
        artifact=ArtifactClass.PRIVATE_OPERATION,
    )
    assert policy.public_shape_allowed(
        ArtifactClass.PUBLIC_COMMITMENT,
        {"schema_version", "policy_version", "commitment", "verified_at"},
    )
    assert not policy.public_shape_allowed(
        ArtifactClass.PUBLIC_COMMITMENT,
        {"commitment", "review_reasoning"},
    )


def test_owner_intent_is_commitment_only_and_never_auto_executable():
    policy = FactoryPolicy()
    payload = {"subnet": 74, "action": "change-emissions", "amount": 0.6}

    intent = policy.intent(
        Role.VALIDATOR,
        ActionKind.EMISSION_CHANGE,
        payload=payload,
        reason="owner approval required after independent validation",
    )

    canonical_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    expected_payload = hashlib.sha256(
        json.dumps({"payload": canonical_payload}, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert intent.payload_commitment == expected_payload
    assert "change-emissions" not in repr(intent)
    assert policy.can_auto_execute(intent) is False


def test_roles_without_proposal_authority_cannot_request_owner_action():
    policy = FactoryPolicy()

    with pytest.raises(FactoryPolicyError, match="scheduler cannot perform propose-owner-action"):
        policy.intent(
            Role.SCHEDULER,
            ActionKind.GITHUB_WRITE,
            payload={"operation": "comment"},
            reason="not allowed",
        )


def test_public_contract_is_static_and_has_no_automatic_owner_path():
    contract = FactoryPolicy().public_contract()

    assert contract["automatic_owner_execution"] is False
    assert contract["automatic_publication"] is False
    assert {item["role"] for item in contract["roles"]} == {role.value for role in Role}
    serialized = json.dumps(contract)
    assert "private-review" not in serialized
    assert "wallet-access" in contract["owner_actions_require_external_approval"]


def test_registry_rejects_a_role_contract_that_grants_owner_effect():
    with pytest.raises(FactoryPolicyError, match="cannot grant owner-level effects"):
        RoleContract(
            role=Role.VALIDATOR,
            purpose="unsafe",
            actions=frozenset({ActionKind.GITHUB_WRITE}),
            readable_memory=frozenset({MemoryScope.ROLE_PRIVATE}),
            writable_memory=frozenset({MemoryScope.ROLE_PRIVATE}),
        )


def test_registry_rejects_stringly_typed_contract_values():
    with pytest.raises(FactoryPolicyError, match="must be ActionKind"):
        RoleContract(
            role=Role.QA,
            purpose="unsafe typing",
            actions=frozenset({"github-write"}),
            readable_memory=frozenset({MemoryScope.ROLE_PRIVATE}),
            writable_memory=frozenset({MemoryScope.ROLE_PRIVATE}),
        )
