"""GitHub host reads the release stage needs: tags, commits since a reference, and the merged pull request."""

from datetime import UTC, datetime

from pytest_httpserver import HTTPServer

from esteward.adapters.github import GithubAdapter
from esteward.models.pull import Pull
from esteward.models.signal import CommitSignal

BRANCH = "esteward/release/v0.2.0"
PULL = {
    "number": 8,
    "node_id": "PR8",
    "head": {"ref": BRANCH},
    "body": "b",
    "auto_merge": None,
    "html_url": "https://github.com/o/r/pull/8",
    "merge_commit_sha": "d" * 40,
    "merged_at": "2026-10-26T12:00:00Z",
}


async def test_tags(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/git/matching-refs/tags/v").respond_with_json(
        [{"ref": "refs/tags/v0.1.0"}, {"ref": "refs/tags/v0.2.0"}]
    )
    assert await github.tags("o/r") == ("v0.1.0", "v0.2.0")


async def test_tags_absent(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/git/matching-refs/tags/v").respond_with_data("", status=404)
    assert await github.tags("o/r") == ()


async def test_commits(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/compare/v0.1.0...HEAD").respond_with_json(
        {
            "commits": [
                {"commit": {"message": "fix: one thing\n\nThe body.", "committer": {"date": "2026-10-20T08:00:00Z"}}},
                {"commit": {"message": "feat: another", "committer": {"date": "2026-10-21T08:00:00Z"}}},
            ]
        }
    )
    assert await github.commits("o/r", "v0.1.0") == (
        CommitSignal("fix: one thing", datetime(2026, 10, 20, 8, 0, tzinfo=UTC)),
        CommitSignal("feat: another", datetime(2026, 10, 21, 8, 0, tzinfo=UTC)),
    )


async def test_commits_at_head(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/compare/v0.2.0...HEAD").respond_with_json({"commits": []})
    assert await github.commits("o/r", "v0.2.0") == ()


async def test_commits_absent(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/compare/v9.9.9...HEAD").respond_with_data("", status=404)
    assert await github.commits("o/r", "v9.9.9") == ()


async def test_merged(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls").respond_with_json([PULL])
    pull = await github.merged("o/r", BRANCH)
    assert pull == Pull(8, "PR8", BRANCH, "b", False, "https://github.com/o/r/pull/8", "d" * 40)
    (request, _) = httpserver.log[0]
    assert request.args["state"] == "closed"
    assert request.args["head"] == f"o:{BRANCH}"


async def test_merged_skips_unmerged(httpserver: HTTPServer, github: GithubAdapter) -> None:
    closed = {**PULL, "merged_at": None}
    httpserver.expect_request("/repos/o/r/pulls").respond_with_json([closed])
    assert await github.merged("o/r", BRANCH) is None


async def test_merged_absent_repository(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls").respond_with_data("", status=404)
    assert await github.merged("o/r", BRANCH) is None
