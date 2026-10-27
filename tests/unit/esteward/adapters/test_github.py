"""GitHub adapter on the wire: absence is None, writes go where they should, other errors raise."""

from datetime import UTC, datetime

import pytest
import wreq
from pytest_httpserver import HTTPServer

from esteward.adapters.github import PIN, PINNED, GithubAdapter
from esteward.models.issue import CloseIssue, CommentIssue, CreateIssue, LabelIssue, PinIssue, UpdateIssue
from esteward.models.signal import RepositorySignal
from tests.unit.esteward.adapters.conftest import (
    ISSUE_BUILT,
    ISSUE_ITEM,
    LISTED_PULL,
    PULL_BUILT,
    PULL_ITEM,
)


async def test_repository(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r", headers={"Authorization": "Bearer secret-token"}).respond_with_json(
        {"full_name": "o/r", "archived": True, "pushed_at": "2026-10-01T08:00:00Z"}
    )
    assert await github.repository("o/r") == RepositorySignal("o/r", True, datetime(2026, 10, 1, 8, 0, tzinfo=UTC))


async def test_repository_anonymous(httpserver: HTTPServer, anonymous_github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_json(
        {"full_name": "O/R", "archived": False, "pushed_at": None}
    )
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
    ).respond_with_json([ISSUE_ITEM, LISTED_PULL])
    assert await github.issues("o/r", "esteward") == (ISSUE_BUILT,)


async def test_issues_united_across_flaky_reads(httpserver: HTTPServer, github: GithubAdapter) -> None:
    """GitHub sometimes answers an empty listing: the union of three reads is what the module sees."""
    listing = "/repos/o/r/issues"
    httpserver.expect_oneshot_request(listing).respond_with_json([])
    httpserver.expect_oneshot_request(listing).respond_with_json([ISSUE_ITEM | {"number": 13}])
    httpserver.expect_request(listing).respond_with_json([ISSUE_ITEM | {"number": 14}])
    assert [issue.number for issue in await github.issues("o/r", "esteward")] == [13, 14]


async def test_open_issues(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/issues", query_string="state=open&per_page=100").respond_with_json(
        [ISSUE_ITEM, LISTED_PULL]
    )
    assert await github.open_issues("o/r") == (ISSUE_BUILT,)


async def test_open_issues_absent(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/issues", query_string="state=open&per_page=100").respond_with_data(
        "", status=404
    )
    assert await github.open_issues("o/r") == ()


async def test_open_pulls(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls", query_string="state=open&per_page=100").respond_with_json([PULL_ITEM])
    assert await github.open_pulls("o/r") == (PULL_BUILT,)


async def test_open_pulls_absent(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls", query_string="state=open&per_page=100").respond_with_data(
        "", status=404
    )
    assert await github.open_pulls("o/r") == ()


async def test_apply_labels_and_comment(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/issues/4/labels", method="POST").respond_with_json({}, status=201)
    httpserver.expect_request("/repos/o/r/issues/4/labels/stale", method="DELETE").respond_with_json({})
    httpserver.expect_request("/repos/o/r/issues/4/labels/other", method="DELETE").respond_with_json({})
    httpserver.expect_request("/repos/o/r/issues/4/comments", method="POST").respond_with_json({}, status=201)
    await github.apply("o/r", LabelIssue(4, add=("community",), remove=("stale",)))
    await github.apply("o/r", LabelIssue(4, remove=("other",)))
    await github.apply("o/r", CommentIssue(4, "x"))
    sent = [(request.method, request.path, request.get_json(silent=True)) for request, _ in httpserver.log]
    assert sent == [
        ("POST", "/repos/o/r/issues/4/labels", {"labels": ["community"]}),
        ("DELETE", "/repos/o/r/issues/4/labels/stale", {}),
        ("DELETE", "/repos/o/r/issues/4/labels/other", {}),
        ("POST", "/repos/o/r/issues/4/comments", {"body": "x"}),
    ]


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


async def test_apply_pin(httpserver: HTTPServer, github: GithubAdapter) -> None:
    """An unpinned issue is pinned: one GraphQL read of the state, one mutation."""
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"repository": {"issue": {"id": "I_1"}, "pinnedIssues": {"nodes": [{"issue": {"number": 42}}]}}}}
    )
    await github.apply("o/r", PinIssue(1))
    sent = [request.get_json() for request, _ in httpserver.log]
    assert sent == [
        {"query": PINNED, "variables": {"owner": "o", "name": "r", "number": 1}},
        {"query": PIN, "variables": {"id": "I_1"}},
    ]


async def test_apply_pin_already(httpserver: HTTPServer, github: GithubAdapter) -> None:
    """Pinning is idempotent: an issue already pinned is skipped, no mutation."""
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"repository": {"issue": {"id": "I_1"}, "pinnedIssues": {"nodes": [{"issue": {"number": 1}}]}}}}
    )
    await github.apply("o/r", PinIssue(1))
    assert [request.get_json()["query"] for request, _ in httpserver.log] == [PINNED]


async def test_apply_pin_absent_issue(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"repository": {"issue": None, "pinnedIssues": {"nodes": []}}}}
    )
    with pytest.raises(ValueError, match="cannot pin"):
        await github.apply("o/r", PinIssue(1))


async def test_repository_moved(httpserver: HTTPServer, github: GithubAdapter) -> None:
    moved = httpserver.url_for("/repositories/42")
    httpserver.expect_request("/repos/old/r").respond_with_data("", status=301, headers={"Location": moved})
    httpserver.expect_request("/repositories/42").respond_with_json(
        {"full_name": "new/r", "archived": False, "pushed_at": None}
    )
    assert await github.repository("old/r") == RepositorySignal("old/r", False, None, moved_to="new/r")


async def test_redirect_followed_once(httpserver: HTTPServer, github: GithubAdapter) -> None:
    loop = httpserver.url_for("/repos/a/b")
    httpserver.expect_request("/repos/a/b").respond_with_data("", status=301, headers={"Location": loop})
    with pytest.raises(ValueError, match="redirected twice"):
        await github.repository("a/b")
