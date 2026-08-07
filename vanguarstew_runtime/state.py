"""Durable, private state for the Vanguarstew runtime.

This database is an operator-local queue, never a public evidence source.  It
stores only operational identifiers and private result locations; raw reviewer
output is written to a separate owner-only directory and is not served over
HTTP or included in runtime status responses.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _secure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


@dataclass(frozen=True)
class ReviewJob:
    """A private unit of pull-request review work."""

    id: int
    delivery_id: str
    repository: str
    pr_number: int
    head_sha: str | None
    attempts: int


class RuntimeState:
    """SQLite-backed queue with atomic claims and owner-only result storage."""

    def __init__(self, database_path: str | Path, private_result_dir: str | Path):
        self.database_path = Path(database_path)
        self.private_result_dir = Path(private_result_dir)
        _secure_directory(self.database_path.parent)
        _secure_directory(self.private_result_dir)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(
            self.database_path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._initialize()
        try:
            self.database_path.chmod(0o600)
        except OSError:
            pass

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY,
                    delivery_id TEXT NOT NULL UNIQUE,
                    repository TEXT NOT NULL,
                    pr_number INTEGER NOT NULL CHECK (pr_number > 0),
                    head_sha TEXT,
                    status TEXT NOT NULL CHECK (status IN
                        ('queued', 'running', 'succeeded', 'deferred', 'failed')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    claimed_at TEXT,
                    result_path TEXT,
                    failure_code TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_status_created
                    ON jobs(status, created_at, id);
                CREATE TABLE IF NOT EXISTS runtime_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "RuntimeState":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def heartbeat(self) -> None:
        now = _utcnow()
        with self._lock:
            self._connection.execute(
                """
                INSERT INTO runtime_meta(key, value, updated_at)
                VALUES ('heartbeat', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (now, now),
            )

    def enqueue_pull_request(
        self,
        *,
        delivery_id: str,
        repository: str,
        pr_number: int,
        head_sha: str | None = None,
    ) -> bool:
        """Add work once.  Duplicate delivery ids are deliberately harmless."""
        if not isinstance(delivery_id, str) or not delivery_id.strip():
            raise ValueError("delivery_id must be a non-empty string")
        if not isinstance(repository, str) or not repository.strip():
            raise ValueError("repository must be a non-empty string")
        if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number <= 0:
            raise ValueError("pr_number must be a positive integer")
        if head_sha is not None and not isinstance(head_sha, str):
            raise ValueError("head_sha must be a string or None")
        now = _utcnow()
        with self._lock:
            cursor = self._connection.execute(
                """
                INSERT INTO jobs(
                    delivery_id, repository, pr_number, head_sha, status, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'queued', 0, ?, ?)
                ON CONFLICT(delivery_id) DO NOTHING
                """,
                (delivery_id.strip(), repository.strip(), pr_number, head_sha, now, now),
            )
        return cursor.rowcount == 1

    def claim_next(self) -> ReviewJob | None:
        """Atomically claim one queued job for this process."""
        now = _utcnow()
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                row = self._connection.execute(
                    """
                    SELECT id, delivery_id, repository, pr_number, head_sha, attempts
                    FROM jobs WHERE status = 'queued' ORDER BY created_at, id LIMIT 1
                    """
                ).fetchone()
                if row is None:
                    self._connection.execute("COMMIT")
                    return None
                cursor = self._connection.execute(
                    """
                    UPDATE jobs
                    SET status='running', attempts=attempts+1, claimed_at=?, updated_at=?
                    WHERE id=? AND status='queued'
                    """,
                    (now, now, row["id"]),
                )
                self._connection.execute("COMMIT")
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
        if cursor.rowcount != 1:
            return None
        return ReviewJob(
            id=int(row["id"]),
            delivery_id=str(row["delivery_id"]),
            repository=str(row["repository"]),
            pr_number=int(row["pr_number"]),
            head_sha=row["head_sha"],
            attempts=int(row["attempts"]) + 1,
        )

    def defer(self, job_id: int, *, code: str) -> None:
        self._transition(job_id, status="deferred", failure_code=code)

    def fail(self, job_id: int, *, code: str) -> None:
        self._transition(job_id, status="failed", failure_code=code)

    def complete(self, job_id: int, *, result_path: str) -> None:
        self._transition(job_id, status="succeeded", result_path=result_path, failure_code=None)

    def _transition(
        self,
        job_id: int,
        *,
        status: str,
        result_path: str | None = None,
        failure_code: str | None = None,
    ) -> None:
        if status not in {"succeeded", "deferred", "failed"}:
            raise ValueError("invalid terminal job status")
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE jobs
                SET status=?, result_path=?, failure_code=?, updated_at=?
                WHERE id=? AND status='running'
                """,
                (status, result_path, failure_code, _utcnow(), job_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("job is not running")

    def requeue_deferred(self) -> int:
        """Return safe, policy-deferred work to the queue after an explicit enablement.

        A dry-run installation must not silently discard a signed webhook or
        poll result.  This method intentionally excludes failed jobs: transport
        or model failures need an operator-visible recovery policy, rather than
        an unbounded retry loop that can spend money or repeatedly hit GitHub.
        """
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE jobs
                SET status='queued', claimed_at=NULL, failure_code=NULL, updated_at=?
                WHERE status='deferred' AND failure_code IN
                    ('dry-run', 'inference-not-explicitly-enabled')
                """,
                (_utcnow(),),
            )
        return cursor.rowcount

    def recover_expired_claims(self, *, lease_seconds: int = 900) -> int:
        """Requeue work left running by a stopped process after its lease expires."""
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or lease_seconds < 1:
            raise ValueError("lease_seconds must be a positive integer")
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).replace(
            microsecond=0
        ).isoformat()
        with self._lock:
            cursor = self._connection.execute(
                """
                UPDATE jobs
                SET status='queued', claimed_at=NULL, failure_code='claim-lease-expired', updated_at=?
                WHERE status='running' AND claimed_at IS NOT NULL AND claimed_at <= ?
                """,
                (_utcnow(), cutoff),
            )
        return cursor.rowcount

    def write_private_result(self, job_id: int, result: dict[str, Any]) -> str:
        """Persist a review result locally with owner-only permissions.

        The returned relative path is an opaque local reference.  No public API
        resolves it, and callers must not put it in GitHub comments, receipts,
        or benchmark artifacts.
        """
        if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
            raise ValueError("job_id must be a positive integer")
        encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        target = self.private_result_dir / f"review-{job_id}.json"
        temporary = self.private_result_dir / f".review-{job_id}.{os.getpid()}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            try:
                target.chmod(0o600)
            except OSError:
                pass
        except Exception:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        return target.name

    def queue_counts(self) -> dict[str, int]:
        """Return aggregate operational counts; no repository or PR data escapes."""
        with self._lock:
            rows = self._connection.execute(
                "SELECT status, COUNT(*) AS total FROM jobs GROUP BY status"
            ).fetchall()
        counts = {"queued": 0, "running": 0, "succeeded": 0, "deferred": 0, "failed": 0}
        counts.update({str(row["status"]): int(row["total"]) for row in rows})
        return counts

    def heartbeat_at(self) -> str | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT value FROM runtime_meta WHERE key='heartbeat'"
            ).fetchone()
        return None if row is None else str(row["value"])
