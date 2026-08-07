import pytest

from vanguarstew_runtime.github import GitHubClient, GitHubError


class _PagingClient(GitHubClient):
    def __init__(self, pages):
        super().__init__("https://api.example.test")
        self.pages = pages
        self.paths = []

    def _get_json(self, path):
        self.paths.append(path)
        page = int(path.rsplit("=", 1)[1])
        return self.pages[page - 1]


def test_paginated_read_includes_all_pages():
    first_page = [{"number": index} for index in range(100)]
    client = _PagingClient([first_page, [{"number": 100}]])

    rows = client.list_open_pull_requests("owner/repository")

    assert len(rows) == 101
    assert client.paths == [
        "/repos/owner/repository/pulls?state=open&per_page=100&page=1",
        "/repos/owner/repository/pulls?state=open&per_page=100&page=2",
    ]


def test_paginated_read_fails_closed_at_safe_limit():
    client = _PagingClient([[{"number": 1}] * 100 for _ in range(30)])

    with pytest.raises(GitHubError, match="safe page limit"):
        client.list_open_pull_requests("owner/repository")
