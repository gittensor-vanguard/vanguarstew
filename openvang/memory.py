"""Encrypted role-private memory and commitment-only factory coordination.

This store is separate from benchmark/controller memory.  It is for local
factory workers and makes two boundaries durable:

* role-private content is encrypted at rest and can be read only through the
  same declared role; and
* cross-role coordination accepts only a caller-supplied SHA-256 commitment.

There is deliberately no method that derives or exports a shared commitment
from a role-private record.  In particular, private maintainer-review material
cannot create a cross-role or public trace through this vault.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import stat
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .factory import ActionKind, FactoryPolicy, MemoryScope, Role


class FactoryMemoryError(RuntimeError):
    """Factory memory storage, encryption, or boundary validation failed."""


class AuthenticatedCipher(Protocol):
    """AEAD-like interface supplied by the local operator or a key service."""

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        """Return authenticated ciphertext bound to ``associated_data``."""

    def decrypt(self, ciphertext: bytes, *, associated_data: bytes) -> bytes:
        """Return plaintext only when ciphertext and associated data verify."""


class FernetMemoryCipher:
    """Optional local Fernet implementation for an operator-managed key.

    ``cryptography`` is intentionally optional so importing the base package
    does not silently add a key-management dependency.  Deployments that use
    this adapter install ``vanguarstew[private-memory]`` and keep the Fernet
    key outside the repository, scheduler, and database.
    """

    def __init__(self, key: bytes | str):
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except ImportError as exc:  # pragma: no cover - depends on install extra
            raise FactoryMemoryError("private memory requires vanguarstew[private-memory]") from exc
        if isinstance(key, str):
            key = key.encode("ascii")
        if not isinstance(key, bytes):
            raise FactoryMemoryError("Fernet memory key must be bytes or ASCII text")
        try:
            self._fernet = Fernet(key)
        except (TypeError, ValueError) as exc:
            raise FactoryMemoryError("Fernet memory key is invalid") from exc
        self._invalid_token = InvalidToken

    @classmethod
    def generate_key(cls) -> bytes:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover - depends on install extra
            raise FactoryMemoryError("private memory requires vanguarstew[private-memory]") from exc
        return Fernet.generate_key()

    def encrypt(self, plaintext: bytes, *, associated_data: bytes) -> bytes:
        if not isinstance(plaintext, bytes) or not isinstance(associated_data, bytes):
            raise FactoryMemoryError("private memory cipher inputs must be bytes")
        # Fernet has no associated-data parameter. Prefixing a fixed-length
        # domain separator and exact AAD lets decryption authenticate both as
        # one token without exposing the AAD in the token plaintext to callers.
        return self._fernet.encrypt(len(associated_data).to_bytes(4, "big") + associated_data + plaintext)

    def decrypt(self, ciphertext: bytes, *, associated_data: bytes) -> bytes:
        if not isinstance(ciphertext, bytes) or not isinstance(associated_data, bytes):
            raise FactoryMemoryError("private memory cipher inputs must be bytes")
        try:
            combined = self._fernet.decrypt(ciphertext)
        except self._invalid_token as exc:
            raise FactoryMemoryError("private memory ciphertext could not be authenticated") from exc
        if len(combined) < 4:
            raise FactoryMemoryError("private memory ciphertext is malformed")
        length = int.from_bytes(combined[:4], "big")
        bound = combined[4 : 4 + length]
        plaintext = combined[4 + length :]
        if len(bound) != length or not hmac.compare_digest(bound, associated_data):
            raise FactoryMemoryError("private memory associated data does not match")
        return plaintext


@dataclass(frozen=True)
class PrivateMemoryRecord:
    """Metadata safe to return after writing encrypted role-private content."""

    id: str
    role: Role
    commitment: str
    created_at: str


@dataclass(frozen=True)
class SharedMemoryCommitment:
    """A shaped coordination fact that contains no role-private payload."""

    id: str
    source_role: Role
    commitment: str
    created_at: str


_MAX_PRIVATE_BYTES = 64 * 1024
_SHA256_HEX = frozenset("0123456789abcdef")


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _canonical_json(value: object) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FactoryMemoryError("private memory content must be JSON-compatible") from exc
    if len(encoded) > _MAX_PRIVATE_BYTES:
        raise FactoryMemoryError("private memory content exceeds the fixed size limit")
    return encoded


def _commitment(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _SHA256_HEX for character in value)
    ):
        raise FactoryMemoryError(f"{label} must be a lowercase SHA-256 commitment")
    return value


def _record_id(value: object) -> str:
    if not isinstance(value, str) or len(value) != 32 or any(character not in _SHA256_HEX for character in value):
        raise FactoryMemoryError("private memory record id is malformed")
    return value


def _associated_data(*, record_id: str, role: Role, commitment: str) -> bytes:
    return f"openvang-private-memory-v1:{record_id}:{role.value}:{commitment}".encode("ascii")


def _secure_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


class FactoryMemoryVault:
    """Owner-local, append-only storage with explicit role and sharing policy."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        cipher: AuthenticatedCipher,
        policy: FactoryPolicy | None = None,
    ):
        if not callable(getattr(cipher, "encrypt", None)) or not callable(getattr(cipher, "decrypt", None)):
            raise TypeError("cipher must provide encrypt and decrypt")
        self.database_path = Path(database_path)
        self.cipher = cipher
        self.policy = policy or FactoryPolicy()
        _secure_directory(self.database_path.parent)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=DELETE")
        self._initialize()
        try:
            self.database_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS private_memory_records (
                    id TEXT PRIMARY KEY,
                    role TEXT NOT NULL,
                    commitment TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS private_memory_role_created
                    ON private_memory_records(role, created_at, id);
                CREATE TABLE IF NOT EXISTS shared_memory_commitments (
                    id TEXT PRIMARY KEY,
                    source_role TEXT NOT NULL,
                    commitment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_role, commitment)
                );
                CREATE INDEX IF NOT EXISTS shared_memory_created
                    ON shared_memory_commitments(created_at, id);
                CREATE TRIGGER IF NOT EXISTS private_memory_records_immutable_update
                    BEFORE UPDATE ON private_memory_records
                    BEGIN SELECT RAISE(ABORT, 'private memory records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS private_memory_records_immutable_delete
                    BEFORE DELETE ON private_memory_records
                    BEGIN SELECT RAISE(ABORT, 'private memory records are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS shared_memory_commitments_immutable_update
                    BEFORE UPDATE ON shared_memory_commitments
                    BEGIN SELECT RAISE(ABORT, 'shared memory commitments are append-only'); END;
                CREATE TRIGGER IF NOT EXISTS shared_memory_commitments_immutable_delete
                    BEFORE DELETE ON shared_memory_commitments
                    BEGIN SELECT RAISE(ABORT, 'shared memory commitments are append-only'); END;
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "FactoryMemoryVault":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def append_private(self, *, role: Role, content: object) -> PrivateMemoryRecord:
        """Encrypt one bounded role-private JSON value and return its metadata."""
        role = Role(role)
        self.policy.assert_allowed(role, ActionKind.WRITE_PRIVATE_MEMORY)
        if not self.policy.can_write_memory(role, MemoryScope.ROLE_PRIVATE):
            raise FactoryMemoryError("role cannot write role-private memory")
        plaintext = _canonical_json(content)
        commitment = hashlib.sha256(plaintext).hexdigest()
        record_id = uuid.uuid4().hex
        created_at = _utcnow()
        try:
            ciphertext = self.cipher.encrypt(
                plaintext,
                associated_data=_associated_data(record_id=record_id, role=role, commitment=commitment),
            )
        except FactoryMemoryError:
            raise
        except Exception as exc:
            raise FactoryMemoryError("private memory encryption failed") from exc
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise FactoryMemoryError("private memory cipher returned invalid ciphertext")
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO private_memory_records(id, role, commitment, ciphertext, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (record_id, role.value, commitment, sqlite3.Binary(ciphertext), created_at),
            )
        return PrivateMemoryRecord(record_id, role, commitment, created_at)

    def read_private(self, *, role: Role, record_id: str) -> object:
        """Decrypt one record only for its exact role; no cross-role fallback exists."""
        role = Role(role)
        self.policy.assert_allowed(role, ActionKind.READ_ROLE_MEMORY)
        if not self.policy.can_read_memory(role, MemoryScope.ROLE_PRIVATE):
            raise FactoryMemoryError("role cannot read role-private memory")
        record_id = _record_id(record_id)
        with self._lock:
            row = self._connection.execute(
                """
                SELECT id, role, commitment, ciphertext
                FROM private_memory_records WHERE id=? AND role=?
                """,
                (record_id, role.value),
            ).fetchone()
        if row is None:
            raise FactoryMemoryError("private memory record is unavailable to this role")
        commitment = _commitment(row["commitment"], label="private memory commitment")
        try:
            plaintext = self.cipher.decrypt(
                bytes(row["ciphertext"]),
                associated_data=_associated_data(record_id=record_id, role=role, commitment=commitment),
            )
        except FactoryMemoryError:
            raise
        except Exception as exc:
            raise FactoryMemoryError("private memory decryption failed") from exc
        if not isinstance(plaintext, bytes) or len(plaintext) > _MAX_PRIVATE_BYTES:
            raise FactoryMemoryError("private memory plaintext is invalid")
        if not hmac.compare_digest(hashlib.sha256(plaintext).hexdigest(), commitment):
            raise FactoryMemoryError("private memory plaintext commitment does not match")
        try:
            value = json.loads(plaintext)
        except (TypeError, ValueError) as exc:
            raise FactoryMemoryError("private memory plaintext is not valid JSON") from exc
        if not hmac.compare_digest(_canonical_json(value), plaintext):
            raise FactoryMemoryError("private memory plaintext is not canonical JSON")
        return value

    def append_shared_commitment(self, *, source_role: Role, commitment: str) -> SharedMemoryCommitment:
        """Persist one already-shaped cross-role commitment without any payload."""
        source_role = Role(source_role)
        self.policy.assert_allowed(source_role, ActionKind.WRITE_PRIVATE_MEMORY)
        if not self.policy.can_write_memory(source_role, MemoryScope.SHARED_COMMITMENT):
            raise FactoryMemoryError("role cannot write shared commitments")
        commitment = _commitment(commitment, label="shared memory commitment")
        record_id = uuid.uuid4().hex
        created_at = _utcnow()
        with self._lock:
            try:
                self._connection.execute(
                    """
                    INSERT INTO shared_memory_commitments(id, source_role, commitment, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (record_id, source_role.value, commitment, created_at),
                )
            except sqlite3.IntegrityError:
                row = self._connection.execute(
                    """
                    SELECT id, source_role, commitment, created_at
                    FROM shared_memory_commitments WHERE source_role=? AND commitment=?
                    """,
                    (source_role.value, commitment),
                ).fetchone()
                assert row is not None
                return _shared_record(row)
        return SharedMemoryCommitment(record_id, source_role, commitment, created_at)

    def shared_commitments(self, *, role: Role, limit: int = 50) -> tuple[SharedMemoryCommitment, ...]:
        """Return bounded commitment-only coordination facts for an allowed role."""
        role = Role(role)
        self.policy.assert_allowed(role, ActionKind.READ_ROLE_MEMORY)
        if not self.policy.can_read_memory(role, MemoryScope.SHARED_COMMITMENT):
            raise FactoryMemoryError("role cannot read shared commitments")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise FactoryMemoryError("shared commitment limit must be between 1 and 100")
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT id, source_role, commitment, created_at
                FROM shared_memory_commitments
                ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(_shared_record(row) for row in rows)

    def counts(self) -> dict[str, int]:
        """Return aggregate local counts only; no content, id, role, or commitment."""
        with self._lock:
            private = self._connection.execute("SELECT COUNT(*) FROM private_memory_records").fetchone()[0]
            shared = self._connection.execute("SELECT COUNT(*) FROM shared_memory_commitments").fetchone()[0]
        return {"private_records": int(private), "shared_commitments": int(shared)}


def _shared_record(row: sqlite3.Row) -> SharedMemoryCommitment:
    try:
        return SharedMemoryCommitment(
            id=_record_id(row["id"]),
            source_role=Role(row["source_role"]),
            commitment=_commitment(row["commitment"], label="shared memory commitment"),
            created_at=str(row["created_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FactoryMemoryError("shared memory record is malformed") from exc
