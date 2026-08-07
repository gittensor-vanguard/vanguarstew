import hashlib
import hmac
import json
from dataclasses import replace
from http.client import HTTPConnection

import pytest

from vanguarstew_runtime.config import load_runtime_config
from vanguarstew_runtime.service import RuntimeService, make_http_server
from vanguarstew_runtime.state import RuntimeState


class _NoNetworkGitHub:
    def list_open_pull_requests(self, repository):
        raise AssertionError("dry run must not poll GitHub")

    def fetch_pull_request(self, repository, number):
        raise AssertionError("dry run must not fetch GitHub")


class _LiveGitHub:
    def list_open_pull_requests(self, repository):
        return []

    def fetch_pull_request(self, repository, number):
        return {
            "number": number,
            "title": "Local fixture",
            "body": "",
            "author": "contributor",
            "additions": 1,
            "deletions": 0,
            "files": ["agent/example.py"],
            "diff": "diff --git a/a b/a",
            "head_sha": "head-1",
        }


class _Reviewer:
    def review(self, pull_request):
        return {"action": "comment", "summary": "stored only locally"}


def _config(tmp_path, *, dry_run=True, webhook_secret=None):
    path = tmp_path / "vanguarstew.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime": {"data_dir": "data", "poll_enabled": True, "poll_seconds": 1},
                "repositories": [{"name": "owner/repository", "enabled": True}],
            }
        )
    )
    environment = {
        "VANGUARSTEW_DRY_RUN": str(dry_run).lower(),
        "VANGUARSTEW_ALLOW_EXTERNAL_INFERENCE": "true",
        "VANGUARSTEW_MODEL": "test-model",
        "VANGUARSTEW_API_BASE": "https://example.test/v1",
        "VANGUARSTEW_API_KEY": "test-key",
    }
    if webhook_secret:
        environment["VANGUARSTEW_WEBHOOK_SECRET"] = webhook_secret
    return load_runtime_config(path, environ=environment)


def test_dry_run_never_calls_github_or_inference(tmp_path):
    config = _config(tmp_path, dry_run=True)
    with RuntimeState(config.database_path, config.private_result_dir) as state:
        state.enqueue_pull_request(delivery_id="event", repository="owner/repository", pr_number=4)
        service = RuntimeService(config, state, github=_NoNetworkGitHub())

        assert service.run_once() == {"queued": 0, "processed": 1}
        assert state.queue_counts()["deferred"] == 1
        assert not list(config.private_result_dir.iterdir())


def test_live_private_review_writes_no_public_result(tmp_path):
    config = _config(tmp_path, dry_run=False)
    with RuntimeState(config.database_path, config.private_result_dir) as state:
        state.enqueue_pull_request(delivery_id="event", repository="owner/repository", pr_number=5)
        service = RuntimeService(config, state, github=_LiveGitHub(), reviewer=_Reviewer())

        assert service.run_once() == {"queued": 0, "processed": 1}
        assert state.queue_counts()["succeeded"] == 1
        results = list(config.private_result_dir.glob("*.json"))
        assert len(results) == 1
        assert "stored only locally" in results[0].read_text()


def test_explicit_live_enablement_requeues_a_dry_run_job(tmp_path):
    dry_config = _config(tmp_path, dry_run=True)
    live_config = _config(tmp_path, dry_run=False)
    with RuntimeState(dry_config.database_path, dry_config.private_result_dir) as state:
        state.enqueue_pull_request(delivery_id="event", repository="owner/repository", pr_number=5)
        RuntimeService(dry_config, state, github=_NoNetworkGitHub()).run_once()
        assert state.queue_counts()["deferred"] == 1

        RuntimeService(live_config, state, github=_LiveGitHub(), reviewer=_Reviewer()).run_once()
        assert state.queue_counts()["succeeded"] == 1


def test_signed_webhook_is_deduplicated_and_health_exposes_no_queue(tmp_path):
    secret = "webhook-secret"
    config = replace(_config(tmp_path, dry_run=True, webhook_secret=secret), port=0)
    with RuntimeState(config.database_path, config.private_result_dir) as state:
        service = RuntimeService(config, state, github=_NoNetworkGitHub())
        body = json.dumps(
            {
                "action": "opened",
                "number": 6,
                "repository": {"full_name": "owner/repository"},
                "pull_request": {"head": {"sha": "head-6"}},
            }
        ).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert service.receive_webhook(body=body, signature=signature, event="pull_request")
        assert not service.receive_webhook(body=body, signature=signature, event="pull_request")

        try:
            server = make_http_server(service)
        except PermissionError:
            pytest.skip("test environment forbids loopback sockets")
        thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            connection = HTTPConnection("127.0.0.1", port, timeout=2)
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            payload = response.read().decode()
            assert response.status == 200
            assert "repository" not in payload
            assert "queued" not in payload
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


def test_signed_webhook_ignores_repositories_outside_local_allow_list(tmp_path):
    secret = "webhook-secret"
    config = _config(tmp_path, dry_run=True, webhook_secret=secret)
    with RuntimeState(config.database_path, config.private_result_dir) as state:
        service = RuntimeService(config, state, github=_NoNetworkGitHub())
        body = json.dumps(
            {
                "action": "opened",
                "number": 7,
                "repository": {"full_name": "other/repository"},
                "pull_request": {"head": {"sha": "head-7"}},
            }
        ).encode()
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        assert not service.receive_webhook(body=body, signature=signature, event="pull_request")
        assert state.queue_counts()["queued"] == 0
