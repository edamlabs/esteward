"""Pull requests the engine opens, GitHub's wire format: found, absent, created, automerged."""

import pytest
from pytest_httpserver import HTTPServer

from esteward.adapters.github import AUTOMERGE, GithubAdapter
from esteward.models.pull import AutomergePull, CreatePull, Pull, UpdatePull

PULL = {
    "number": 5,
    "node_id": "PR5",
    "head": {"ref": "esteward/act/x"},
    "body": "b",
    "auto_merge": {"merge_method": "squash"},
    "html_url": "https://github.com/o/r/pull/5",
}


async def test_pull_found(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls").respond_with_json([PULL])
    assert await github.pull("o/r", "esteward/act/x") == Pull(
        5, "PR5", "esteward/act/x", "b", True, "https://github.com/o/r/pull/5"
    )
    (request, _) = httpserver.log[0]
    assert request.args["state"] == "open"
    assert request.args["head"] == "o:esteward/act/x"


async def test_pull_empty_listing(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls").respond_with_json([])
    assert await github.pull("o/r", "br") is None


async def test_pull_absent_repository(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r/pulls").respond_with_data("", status=404)
    assert await github.pull("o/r", "br") is None


async def test_apply_pull(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_json({"default_branch": "main"})
    httpserver.expect_request("/repos/o/r/pulls", method="POST").respond_with_json(PULL, status=201)
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"enablePullRequestAutoMerge": {"clientMutationId": "1"}}}
    )
    httpserver.expect_request("/repos/o/r/pulls/5", method="PATCH").respond_with_json({})
    await github.apply("o/r", CreatePull("esteward/act/x", "t", "b"))
    await github.apply("o/r", UpdatePull(5, "b2"))
    await github.apply("o/r", AutomergePull("PR9"))
    sent = [(request.method, request.path, request.get_json(silent=True)) for request, _ in httpserver.log]
    assert sent == [
        ("GET", "/repos/o/r", None),
        ("POST", "/repos/o/r/pulls", {"title": "t", "head": "esteward/act/x", "base": "main", "body": "b"}),
        ("POST", "/graphql", {"query": AUTOMERGE, "variables": {"node": "PR5"}}),
        ("PATCH", "/repos/o/r/pulls/5", {"body": "b2"}),
        ("POST", "/graphql", {"query": AUTOMERGE, "variables": {"node": "PR9"}}),
    ]


async def test_create_pull_absent_repository(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/repos/o/r").respond_with_data("", status=404)
    with pytest.raises(ValueError, match="repository o/r not found"):
        await github.apply("o/r", CreatePull("br", "t", "b"))


async def test_graphql_errors_raise(httpserver: HTTPServer, github: GithubAdapter) -> None:
    httpserver.expect_request("/graphql", method="POST").respond_with_json({"errors": [{"message": "boom"}]})
    with pytest.raises(ValueError, match="boom"):
        await github.apply("o/r", AutomergePull("PR9"))
