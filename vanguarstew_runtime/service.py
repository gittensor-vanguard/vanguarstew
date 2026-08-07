"""Private, durable execution loop for self-hosted maintainer assistance."""

from __future__ import annotations

import hmac
import json
import logging
import threading
from hashlib import sha256
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from agent.llm import LLM
from agent.review import review_pr

from .config import RuntimeConfig
from .github import GitHubClient, GitHubError
from .state import ReviewJob, RuntimeState

logger = logging.getLogger(__name__)


class PullRequestReader(Protocol):
    """Read-only source of pull-request metadata and diffs."""

    def list_open_pull_requests(self, repository: str) -> list[dict[str, Any]]:
        ...

    def fetch_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        ...


class ReviewExecutor(Protocol):
    """A private review implementation that returns a structured local result."""

    def review(self, pull_request: dict[str, Any]) -> dict[str, Any]:
        ...


class AgentReviewExecutor:
    """Run the existing maintainer-assist review against managed inference."""

    def __init__(self, config: RuntimeConfig):
        self._config = config

    def review(self, pull_request: dict[str, Any]) -> dict[str, Any]:
        llm = LLM(
            model=self._config.model,
            api_base=self._config.api_base,
            api_key=self._config.api_key,
        )
        return review_pr(pull_request, None, llm)


class RuntimeService:
    """Poll and process review work while retaining all reviewer output locally.

    Safety is enforced in the execution flow, rather than only documented:

    * a dry run never calls GitHub or an inference provider;
    * live inference requires an explicit environment opt-in; and
    * no execution path sends a review result back to GitHub or a public API.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        state: RuntimeState,
        *,
        github: PullRequestReader | None = None,
        reviewer: ReviewExecutor | None = None,
    ):
        self.config = config
        self.state = state
        self.github = github or GitHubClient(config.github_api_base, config.github_token)
        self.reviewer = reviewer or AgentReviewExecutor(config)
        self._stop_event = threading.Event()

    @property
    def is_ready(self) -> bool:
        return self.state.database_path.exists()

    def request_stop(self) -> None:
        self._stop_event.set()

    def receive_webhook(self, *, body: bytes, signature: str | None, event: str | None) -> bool:
        """Validate and enqueue an actionable GitHub pull-request delivery.

        False means the delivery was valid but irrelevant or already seen.  No
        review information is returned to the caller.
        """
        secret = self.config.webhook_secret
        if not secret:
            raise PermissionError("webhook receiver is disabled")
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise PermissionError("webhook signature did not match")
        if event != "pull_request":
            return False
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("webhook body was not valid JSON") from exc
        if not isinstance(payload, dict) or payload.get("action") not in {
            "opened",
            "reopened",
            "synchronize",
            "ready_for_review",
        }:
            return False
        repository = payload.get("repository")
        pull_request = payload.get("pull_request")
        if not isinstance(repository, dict) or not isinstance(pull_request, dict):
            raise ValueError("webhook did not contain pull-request metadata")
        full_name = repository.get("full_name")
        number = payload.get("number")
        allowed_repositories = {target.name.lower() for target in self.config.enabled_repositories}
        if not isinstance(full_name, str) or full_name.lower() not in allowed_repositories:
            # A correctly signed delivery can still be for another installation
            # or repository.  Do not turn it into private review work unless it
            # is explicitly in the local allow-list.
            return False
        head = pull_request.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) else None
        delivery_id = sha256(body).hexdigest()
        return self.state.enqueue_pull_request(
            delivery_id=f"webhook:{delivery_id}",
            repository=full_name,
            pr_number=number,
            head_sha=head_sha if isinstance(head_sha, str) else None,
        )

    def poll_once(self) -> int:
        """Queue current open PR heads using read-only GitHub API requests."""
        if not self.config.poll_enabled or self.config.dry_run:
            return 0
        queued = 0
        for target in self.config.enabled_repositories:
            try:
                pull_requests = self.github.list_open_pull_requests(target.name)
            except GitHubError:
                # Keep this deliberately repository-free: runtime logs must not
                # become a public trace of private reviewer activity.
                logger.warning("GitHub polling failed; the runtime will retry next cycle")
                continue
            for pull_request in pull_requests:
                number = pull_request.get("number")
                head = pull_request.get("head")
                head_sha = head.get("sha") if isinstance(head, dict) else None
                if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
                    continue
                delivery_id = f"poll:{target.name}:{number}:{head_sha or 'unknown'}"
                if self.state.enqueue_pull_request(
                    delivery_id=delivery_id,
                    repository=target.name,
                    pr_number=number,
                    head_sha=head_sha if isinstance(head_sha, str) else None,
                ):
                    queued += 1
        return queued

    def process_one(self) -> str | None:
        """Process at most one job and return only its terminal status."""
        job = self.state.claim_next()
        if job is None:
            return None
        if self.config.dry_run:
            self.state.defer(job.id, code="dry-run")
            return "deferred"
        if not self.config.can_run_inference:
            self.state.defer(job.id, code="inference-not-explicitly-enabled")
            return "deferred"
        return self._review(job)

    def _review(self, job: ReviewJob) -> str:
        try:
            pull_request = self.github.fetch_pull_request(job.repository, job.pr_number)
            review = self.reviewer.review(pull_request)
            result = {
                "schema_version": 1,
                "review": review,
                "reviewed_head_sha": pull_request.get("head_sha"),
            }
            result_path = self.state.write_private_result(job.id, result)
            self.state.complete(job.id, result_path=result_path)
            return "succeeded"
        except GitHubError:
            logger.warning("GitHub read failed while preparing local review")
            self.state.fail(job.id, code="github-read-failed")
            return "failed"
        except (OSError, ValueError, TypeError):
            # This covers transport/model failures and malformed provider output
            # without emitting a PR identifier or review content to logs.
            logger.warning("Private review did not complete")
            self.state.fail(job.id, code="private-review-failed")
            return "failed"

    def run_once(self) -> dict[str, int]:
        """Record a heartbeat and complete a bounded amount of work."""
        self.state.recover_expired_claims()
        if not self.config.dry_run and self.config.can_run_inference:
            self.state.requeue_deferred()
        self.state.heartbeat()
        queued = self.poll_once()
        processed = 0
        for _ in range(self.config.max_jobs_per_cycle):
            if self.process_one() is None:
                break
            processed += 1
        return {"queued": queued, "processed": processed}

    def serve_forever(self) -> None:
        """Run bounded cycles until an operator or signal requests shutdown."""
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self.config.poll_seconds)


def make_http_server(service: RuntimeService) -> ThreadingHTTPServer:
    """Create a loopback-oriented health and webhook server.

    There is purposely no endpoint for queue entries, review decisions, source
    evidence, prompts, or result files.  Health endpoints contain static state
    only and can safely be used by a local process supervisor.
    """

    class RuntimeHandler(BaseHTTPRequestHandler):
        server_version = "VanguarstewRuntime/0.8"

        def log_message(self, format: str, *args: object) -> None:
            # The default request log includes URLs and remote addresses.  Do
            # not create an operational activity trail by default.
            return

        def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - HTTP handler API
            if self.path == "/healthz":
                self._json(HTTPStatus.OK, {"ok": True, "service": "vanguarstew"})
                return
            if self.path == "/readyz":
                self._json(HTTPStatus.OK if service.is_ready else HTTPStatus.SERVICE_UNAVAILABLE, {"ok": service.is_ready})
                return
            self._json(HTTPStatus.NOT_FOUND, {"ok": False})

        def do_POST(self) -> None:  # noqa: N802 - HTTP handler API
            if self.path != "/webhooks/github":
                self._json(HTTPStatus.NOT_FOUND, {"ok": False})
                return
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "")
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False})
                return
            if length < 1 or length > 1_000_000:
                self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"ok": False})
                return
            body = self.rfile.read(length)
            try:
                accepted = service.receive_webhook(
                    body=body,
                    signature=self.headers.get("X-Hub-Signature-256"),
                    event=self.headers.get("X-GitHub-Event"),
                )
            except PermissionError:
                self._json(HTTPStatus.UNAUTHORIZED, {"ok": False})
                return
            except ValueError:
                self._json(HTTPStatus.BAD_REQUEST, {"ok": False})
                return
            self._json(HTTPStatus.ACCEPTED, {"ok": accepted})

    return ThreadingHTTPServer((service.config.host, service.config.port), RuntimeHandler)


def serve_with_http(service: RuntimeService) -> None:
    """Serve local health/webhook requests while the private worker runs."""
    server = make_http_server(service)
    thread = threading.Thread(target=server.serve_forever, name="vanguarstew-http", daemon=True)
    thread.start()
    try:
        service.serve_forever()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
