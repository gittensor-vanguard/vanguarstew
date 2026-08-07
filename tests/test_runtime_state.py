import json
import stat

import pytest

from vanguarstew_runtime.state import RuntimeState


def _state(tmp_path):
    return RuntimeState(tmp_path / "data" / "runtime.sqlite3", tmp_path / "data" / "private")


def test_state_deduplicates_delivery_and_claims_once(tmp_path):
    with _state(tmp_path) as state:
        assert state.enqueue_pull_request(
            delivery_id="delivery-1", repository="owner/repo", pr_number=7, head_sha="abc"
        )
        assert not state.enqueue_pull_request(
            delivery_id="delivery-1", repository="owner/repo", pr_number=7, head_sha="abc"
        )

        job = state.claim_next()
        assert job is not None
        assert job.pr_number == 7
        assert state.claim_next() is None
        state.defer(job.id, code="dry-run")
        assert state.queue_counts() == {
            "queued": 0,
            "running": 0,
            "succeeded": 0,
            "deferred": 1,
            "failed": 0,
        }


def test_state_private_result_is_owner_readable_and_not_in_queue_counts(tmp_path):
    with _state(tmp_path) as state:
        assert state.enqueue_pull_request(delivery_id="delivery-2", repository="owner/repo", pr_number=8)
        job = state.claim_next()
        path_name = state.write_private_result(job.id, {"summary": "private review"})
        state.complete(job.id, result_path=path_name)

        result_path = state.private_result_dir / path_name
        assert json.loads(result_path.read_text()) == {"summary": "private review"}
        assert stat.S_IMODE(result_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(state.private_result_dir.stat().st_mode) == 0o700
        assert state.queue_counts()["succeeded"] == 1


def test_state_refuses_terminal_transition_for_non_running_job(tmp_path):
    with _state(tmp_path) as state:
        with pytest.raises(ValueError, match="not running"):
            state.fail(999, code="missing")


def test_state_recovers_expired_running_claim_but_not_a_fresh_one(tmp_path):
    with _state(tmp_path) as state:
        state.enqueue_pull_request(delivery_id="stale", repository="owner/repo", pr_number=9)
        state.enqueue_pull_request(delivery_id="fresh", repository="owner/repo", pr_number=10)
        stale = state.claim_next()
        fresh = state.claim_next()
        state._connection.execute(
            "UPDATE jobs SET claimed_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", stale.id)
        )

        assert state.recover_expired_claims(lease_seconds=3600) == 1
        assert state.queue_counts()["queued"] == 1
        assert state.queue_counts()["running"] == 1
        assert fresh.id != stale.id
