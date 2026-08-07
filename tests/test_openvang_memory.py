"""Contract tests for encrypted role-private OpenVang factory memory."""

from __future__ import annotations

import hashlib
import sqlite3
import stat

import pytest

from openvang.factory import Role
from openvang.memory import FactoryMemoryError, FactoryMemoryVault, FernetMemoryCipher


def _vault(tmp_path, *, key=None):
    cipher = FernetMemoryCipher(key or FernetMemoryCipher.generate_key())
    return FactoryMemoryVault(tmp_path / "factory-memory" / "vault.sqlite3", cipher=cipher), cipher


def test_role_private_memory_is_encrypted_append_only_and_role_scoped(tmp_path):
    vault, _cipher = _vault(tmp_path)
    private_content = {"review": "private-review-marker", "decision": "request changes"}
    record = vault.append_private(role=Role.MAINTAINER, content=private_content)

    assert record.role == Role.MAINTAINER
    assert record.commitment == hashlib.sha256(
        b'{"decision":"request changes","review":"private-review-marker"}'
    ).hexdigest()
    assert vault.read_private(role=Role.MAINTAINER, record_id=record.id) == private_content
    with pytest.raises(FactoryMemoryError, match="unavailable to this role"):
        vault.read_private(role=Role.QA, record_id=record.id)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        vault._connection.execute("UPDATE private_memory_records SET role='qa' WHERE id=?", (record.id,))

    assert b"private-review-marker" not in vault.database_path.read_bytes()
    assert stat.S_IMODE(vault.database_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(vault.database_path.parent.stat().st_mode) == 0o700
    assert vault.counts() == {"private_records": 1, "shared_commitments": 0}
    vault.close()


def test_private_memory_rejects_a_wrong_key_without_exposing_content(tmp_path):
    vault, _cipher = _vault(tmp_path)
    record = vault.append_private(role=Role.SECURITY_QA, content={"finding": "private-marker"})
    vault.close()

    wrong_key = FernetMemoryCipher.generate_key()
    reopened = FactoryMemoryVault(vault.database_path, cipher=FernetMemoryCipher(wrong_key))
    with pytest.raises(FactoryMemoryError, match="could not be authenticated"):
        reopened.read_private(role=Role.SECURITY_QA, record_id=record.id)
    reopened.close()


def test_cross_role_coordination_accepts_only_shaped_commitments(tmp_path):
    vault, _cipher = _vault(tmp_path)
    private_record = vault.append_private(role=Role.MAINTAINER, content={"note": "do not share"})
    commitment = "ab" * 32

    shared = vault.append_shared_commitment(source_role=Role.MAINTAINER, commitment=commitment)
    duplicate = vault.append_shared_commitment(source_role=Role.MAINTAINER, commitment=commitment)

    assert duplicate == shared
    assert vault.shared_commitments(role=Role.QA) == (shared,)
    with pytest.raises(FactoryMemoryError, match="SHA-256 commitment"):
        vault.append_shared_commitment(source_role=Role.MAINTAINER, commitment=private_record.id)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        vault._connection.execute(
            "UPDATE shared_memory_commitments SET source_role='qa' WHERE id=?", (shared.id,)
        )
    assert b"do not share" not in vault.database_path.read_bytes()
    vault.close()


def test_private_memory_rejects_noncanonical_or_oversized_content(tmp_path):
    vault, _cipher = _vault(tmp_path)
    with pytest.raises(FactoryMemoryError, match="JSON-compatible"):
        vault.append_private(role=Role.BUILDER, content={"unsupported": {1, 2}})
    with pytest.raises(FactoryMemoryError, match="size limit"):
        vault.append_private(role=Role.BUILDER, content={"large": "x" * (64 * 1024)})
    vault.close()
