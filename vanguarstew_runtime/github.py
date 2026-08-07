"""Minimal read-only GitHub client used by the private runtime.

There are intentionally no methods for comments, labels, closing, approving,
merging, releases, or other mutations.  The runtime can gather a PR for a
local review but cannot publish or act on that review.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHubError(RuntimeError):
    """A read-only GitHub request could not be completed."""


@dataclass(frozen=True)
class GitHubClient:
    api_base: str
    token: str | None = None
    timeout: float = 30.0

    def _get_json(self, path: str) -> Any:
        payload = self._get(path, accept="application/vnd.github+json")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GitHubError("GitHub returned malformed JSON") from exc

    def _get(self, path: str, *, accept: str) -> bytes:
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "vanguarstew-runtime/0.8",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(f"{self.api_base.rstrip('/')}{path}", headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code in {401, 403}:
                raise GitHubError("GitHub authentication or rate limit rejected the read request") from exc
            if exc.code == 404:
                raise GitHubError("GitHub pull request or repository was not found") from exc
            raise GitHubError(f"GitHub read request failed with HTTP {exc.code}") from exc
        except (URLError, OSError) as exc:
            raise GitHubError("GitHub read request could not reach the API") from exc

    def _get_paginated_array(self, path: str, *, maximum_pages: int = 30) -> list[dict[str, Any]]:
        """Read a complete bounded GitHub list rather than silently reviewing a prefix.

        A pull request with more than one files page must not be reviewed from
        only its first hundred paths.  The bound avoids turning one event into
        an unbounded sequence of API requests; reaching it fails closed.
        """
        separator = "&" if "?" in path else "?"
        result = []
        for page in range(1, maximum_pages + 1):
            data = self._get_json(f"{path}{separator}page={page}")
            if not isinstance(data, list):
                raise GitHubError("GitHub list response was not an array")
            result.extend(entry for entry in data if isinstance(entry, dict))
            if len(data) < 100:
                return result
        raise GitHubError("GitHub list exceeds the configured safe page limit")

    @staticmethod
    def _path_repository(repository: str) -> str:
        owner, name = repository.split("/", 1)
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def list_open_pull_requests(self, repository: str) -> list[dict[str, Any]]:
        return self._get_paginated_array(
            f"{self._path_repository(repository)}/pulls?state=open&per_page=100"
        )

    def fetch_pull_request(self, repository: str, number: int) -> dict[str, Any]:
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError("pull-request number must be a positive integer")
        base = f"{self._path_repository(repository)}/pulls/{number}"
        data = self._get_json(base)
        if not isinstance(data, dict):
            raise GitHubError("GitHub pull-request response was not an object")
        files_data = self._get_paginated_array(f"{base}/files?per_page=100")
        diff = self._get(base, accept="application/vnd.github.v3.diff")
        author = data.get("user")
        login = author.get("login") if isinstance(author, dict) else None
        files = [
            entry.get("filename")
            for entry in files_data
            if isinstance(entry, dict) and isinstance(entry.get("filename"), str)
        ]
        head = data.get("head")
        head_sha = head.get("sha") if isinstance(head, dict) and isinstance(head.get("sha"), str) else None
        return {
            "number": data.get("number", number),
            "title": data.get("title", ""),
            "body": data.get("body"),
            "author": login or "ghost",
            "additions": data.get("additions", 0),
            "deletions": data.get("deletions", 0),
            "files": files,
            "diff": diff.decode("utf-8", errors="replace"),
            "head_sha": head_sha,
        }
