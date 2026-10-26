"""The workspace adapter on real git: clones, tool runs, commits, pushes, restores, credential injection."""

import base64
from datetime import timedelta
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.adapters.workspace import WorkspaceAdapter
from esteward.models.outcome import RunOutcome
from tests.unit.esteward.adapters.conftest import IDENTITY, git


async def test_checkout_read(workspace: WorkspaceAdapter) -> None:
    await workspace.checkout("o/r")
    assert await workspace.read("uv.lock") == "original\n"
    assert await workspace.read("absent.lock") is None


async def test_run(workspace: WorkspaceAdapter) -> None:
    await workspace.checkout("o/r")
    outcome = await workspace.run(("git", "rev-parse", "--abbrev-ref", "HEAD"))
    assert outcome == RunOutcome(0, "main\n", "")


async def test_run_failure_is_data(workspace: WorkspaceAdapter) -> None:
    await workspace.checkout("o/r")
    outcome = await workspace.run(("git", "rev-parse", "--verify", "absent-ref"))
    assert outcome.rc != 0
    assert "Needed a single revision" in outcome.err


async def test_before_checkout(workspace: WorkspaceAdapter) -> None:
    with pytest.raises(RuntimeError, match="not checked out"):
        await workspace.run(("git", "status"))


async def test_commit_push_restore(workspace: WorkspaceAdapter, remote: Path) -> None:
    await workspace.checkout("o/r")
    assert await workspace.commit("esteward/act/br", "nothing to do") is False
    await workspace.run(("sh", "-c", "echo bumped > uv.lock"))
    assert await workspace.commit("esteward/act/br", "bump") is True
    await workspace.push("esteward/act/br")
    assert "refs/heads/esteward/act/br" in git("-C", str(remote / "o" / "r.git"), "for-each-ref", "refs/heads")
    assert (await workspace.run(("git", "log", "-1", "--format=%an <%ae>"))).out.strip() == IDENTITY
    await workspace.run(("sh", "-c", "echo dirty >> uv.lock && echo junk > junk.txt"))
    await workspace.restore()
    assert await workspace.read("uv.lock") == "original\n"
    assert await workspace.read("junk.txt") is None
    assert await workspace.commit("esteward/act/again", "nothing to do") is False


async def test_checkout_replaces(workspace: WorkspaceAdapter) -> None:
    await workspace.checkout("o/r")
    await workspace.run(("sh", "-c", "echo dirty > uv.lock"))
    await workspace.checkout("o/r")
    assert await workspace.read("uv.lock") == "original\n"


async def test_clone_failure(tmp_path: Path, remote: Path) -> None:
    adapter = WorkspaceAdapter(tmp_path / "work", str(remote / "absent" / "{slug}.git"), None, timedelta(minutes=1))
    with pytest.raises(RuntimeError, match="clone of o/r failed"):
        await adapter.checkout("o/r")


async def test_push_failure(workspace: WorkspaceAdapter) -> None:
    """A git that must succeed and does not is an infrastructure fault: it raises with git's own words."""
    await workspace.checkout("o/r")
    await workspace.run(("sh", "-c", "echo bumped > uv.lock"))
    assert await workspace.commit("br", "bump") is True
    await workspace.run(("git", "remote", "set-url", "origin", "/nonexistent/o/r.git"))
    with pytest.raises(RuntimeError, match="git push failed"):
        await workspace.push("br")


async def test_write(workspace: WorkspaceAdapter) -> None:
    await workspace.checkout("o/r")
    await workspace.write("uv.lock", "bumped\n")
    assert await workspace.read("uv.lock") == "bumped\n"


async def test_tag(workspace: WorkspaceAdapter, remote: Path) -> None:
    """The tag lands on the exact revision, in the bare remote, where the release flow picks it up."""
    await workspace.checkout("o/r")
    head = (await workspace.run(("git", "rev-parse", "HEAD"))).out.strip()
    await workspace.tag("v0.2.0", head)
    assert "refs/tags/v0.2.0" in git("-C", str(remote / "o" / "r.git"), "for-each-ref", "refs/tags")
    tagged = git("-C", str(remote / "o" / "r.git"), "rev-list", "-n", "1", "v0.2.0").strip()
    assert tagged == head


async def test_tag_of_unfetched_revision(workspace: WorkspaceAdapter) -> None:
    """A revision outside the shallow clone is fetched before the tag: the release PR's merge commit."""
    await workspace.checkout("o/r")
    with pytest.raises(RuntimeError, match="git fetch failed"):
        await workspace.tag("v0.2.0", "a" * 40)


async def test_timeout(workspace: WorkspaceAdapter, monkeypatch: pytest.MonkeyPatch) -> None:
    """The tool timeout is the adapter's only clock: shrunk here so `sleep 30` dies at once."""
    await workspace.checkout("o/r")
    monkeypatch.setattr(workspace, "_timeout", 0.05)
    with pytest.raises(TimeoutError, match="timed out"):
        await workspace.run(("sleep", "30"))


async def test_remote_token_http(httpserver: HTTPServer, tmp_path: Path) -> None:
    """An http(s) remote is cloned with the token as the password, never asked interactively."""
    httpserver.expect_request("/o/r.git/info/refs").respond_with_data(
        "", status=401, headers={"WWW-Authenticate": 'Basic realm="git"'}
    )
    adapter = WorkspaceAdapter(tmp_path / "work", httpserver.url_for("/{slug}.git"), "sekrit", timedelta(minutes=1))
    with pytest.raises(RuntimeError, match="clone of o/r failed"):
        await adapter.checkout("o/r")
    expected = f"Basic {base64.b64encode(b'x-access-token:sekrit').decode()}"
    assert expected in [request.headers.get("Authorization") for request, _ in httpserver.log]


async def test_remote_token_other_scheme(remote: Path, tmp_path: Path) -> None:
    """A non-http remote keeps its URL: a token has no place in a file path."""
    adapter = WorkspaceAdapter(tmp_path / "work", f"file://{remote}/{{slug}}.git", "sekrit", timedelta(minutes=1))
    await adapter.checkout("o/r")
    assert await adapter.read("uv.lock") == "original\n"
