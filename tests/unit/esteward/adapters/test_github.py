"""GitHub adapter on the wire: absence is None, writes go where they should, other errors raise."""

from datetime import UTC, datetime

import pytest
import wreq
from pytest_httpserver import HTTPServer

from esteward.adapters.github import GithubAdapter
from esteward.models.issue import CloseIssue, CreateIssue, Issue, UpdateIssue
from esteward.models.signal import RepositorySignal


async def test_repository(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r", headers={"Authorization": "Bearer secret-token"}).respond_with_json(
        {"archived": True, "pushed_at": "2026-10-01T08:00:00Z"}
    )
    assert await github.repository("o/r") == RepositorySignal("o/r", True, datetime(2026, 10, 1, 8, 0, tzinfo=UTC))


async def test_repository_anonymous(httpserver: HTTPServer, anonymous_github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_json({"archived": False, "pushed_at": None})
    assert await anonymous_github.repository("o/r") == RepositorySignal("o/r", False, None)
    assert "Authorization" not in httpserver.log[0][0].headers


@pytest.mark.parametrize("status", [404, 422], ids=["not-found", "unprocessable"])
async def test_absent(httpserver: HTTPServer, github: GithubAdapter, status: int) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_data("", status=status)
    httpserver.expect_request("/repos/o/r/contents/x.toml").respond_with_data("", status=status)
    httpserver.expect_request("/repos/o/r/git/trees/HEAD").respond_with_data("", status=status)
    httpserver.expect_request("/repos/o/r/commits/abc").respond_with_data("", status=status)
    httpserver.expect_request("/repos/o/r/issues").respond_with_data("", status=status)
    assert await github.repository("o/r") is None
    assert await github.file("o/r", "x.toml") is None
    assert await github.tree("o/r") == ()
    assert await github.commit("o/r", "abc") is False
    assert await github.issues("o/r", "esteward") == ()


async def test_server_error_raises(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_data("boom", status=500)
    with pytest.raises(wreq.StatusError):
        await github.repository("o/r")


async def test_file_tree_commit(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request(
        "/repos/o/r/contents/a b.yml", headers={"Accept": "application/vnd.github.raw+json"}
    ).respond_with_data("raw")
    httpserver.expect_request("/repos/o/r/git/trees/HEAD", query_string="recursive=1").respond_with_json(
        {"tree": [{"path": "a.yml", "type": "blob"}, {"path": "dir", "type": "tree"}]}
    )
    httpserver.expect_request("/repos/o/r/commits/abc").respond_with_json({"sha": "abc"})
    assert await github.file("o/r", "a b.yml") == "raw"
    assert await github.tree("o/r") == ("a.yml",)
    assert await github.commit("o/r", "abc") is True


async def test_issues(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request(
        "/repos/o/r/issues", query_string="labels=esteward&state=open&per_page=100"
    ).respond_with_json(
        [{"number": 1, "title": "t", "body": None}, {"number": 2, "title": "pr", "body": "x", "pull_request": {}}]
    )
    assert await github.issues("o/r", "esteward") == (Issue(1, "t", ""),)


async def test_apply(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/issues", method="POST").respond_with_json({}, status=201)
    httpserver.expect_request("/repos/o/r/issues/7", method="PATCH").respond_with_json({})
    httpserver.expect_request("/repos/o/r/issues/9/comments", method="POST").respond_with_json({}, status=201)
    httpserver.expect_request("/repos/o/r/issues/9", method="PATCH").respond_with_json({})
    await github.apply("o/r", CreateIssue("t", "b", ("esteward",)))
    await github.apply("o/r", UpdateIssue(7, "t2", "b2"))
    await github.apply("o/r", CloseIssue(9, "cleared"))
    sent = [(request.method, request.path, request.get_json()) for request, _ in httpserver.log]
    assert sent == [
        ("POST", "/repos/o/r/issues", {"title": "t", "body": "b", "labels": ["esteward"]}),
        ("PATCH", "/repos/o/r/issues/7", {"title": "t2", "body": "b2"}),
        ("POST", "/repos/o/r/issues/9/comments", {"body": "cleared"}),
        ("PATCH", "/repos/o/r/issues/9", {"state": "closed", "state_reason": "completed"}),
    ]


async def test_issues_united_across_flaky_reads(httpserver: HTTPServer, github: GithubAdapter) -> None:
    listing = "/repos/o/r/issues"
    httpserver.expect_oneshot_request(listing).respond_with_json([])
    httpserver.expect_oneshot_request(listing).respond_with_json([{"number": 13, "title": "s", "body": "b"}])
    httpserver.expect_request(listing).respond_with_json([{"number": 14, "title": "s", "body": "b"}])
    assert [issue.number for issue in await github.issues("o/r", "esteward")] == [13, 14]
