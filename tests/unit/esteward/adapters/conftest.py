"""A real HTTP client against a local server: adapters are tested on the wire, no mocks."""

import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
import wreq
from pytest_httpserver import HTTPServer

from esteward.adapters.crates import CratesAdapter
from esteward.adapters.github import GithubAdapter
from esteward.adapters.osv import OsvAdapter
from esteward.adapters.pypi import PypiAdapter
from esteward.adapters.workspace import WorkspaceAdapter
from esteward.models.issue import Issue
from esteward.models.pull import TriagePull

AGENT = "esteward-test"
IDENTITY = "esteward[bot] <eself-maintenance[bot]@users.noreply.github.com>"

##### TRACKER PAYLOADS #####

### One item as the tracker answers it: the listing of issues and the listing of pulls read the same fields.
ISSUE_ITEM: Final[dict[str, Any]] = {
    "number": 1,
    "title": "t",
    "body": None,
    "user": {"login": "stranger"},
    "author_association": "NONE",
    "labels": [{"name": "bug"}],
    "updated_at": "2026-10-01T00:00:00Z",
}
ISSUE_BUILT: Final = Issue(
    number=1,
    title="t",
    body="",
    author="stranger",
    association="NONE",
    labels=("bug",),
    updated=datetime(2026, 10, 1, tzinfo=UTC),
)
PULL_ITEM: Final[dict[str, Any]] = {**ISSUE_ITEM, "number": 5, "draft": True}
PULL_BUILT: Final = TriagePull(
    number=5,
    author="stranger",
    association="NONE",
    labels=("bug",),
    updated=datetime(2026, 10, 1, tzinfo=UTC),
    draft=True,
)
### A pull request inside the issues listing: `/issues` returns both, the tracker keeps them apart by this key.
LISTED_PULL: Final[dict[str, Any]] = {"number": 2, "title": "pr", "body": "x", "pull_request": {}}


def git(*argv: str) -> str:
    """One git command in the fixtures' identity, its stdout."""
    done = subprocess.run(
        ("git", "-c", "user.name=test", "-c", "user.email=test@test", *argv), capture_output=True, text=True, check=True
    )
    return done.stdout


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare git repository seeded with one file, standing in for the code host: `remote/o/r.git`."""
    bare = tmp_path / "remote" / "o" / "r.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(("git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)), check=True)
    seed = tmp_path / "seed"
    subprocess.run(("git", "clone", "--quiet", str(bare), str(seed)), check=True)
    (seed / "uv.lock").write_text("original\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(seed), "add", "-A"), check=True)
    subprocess.run(
        (
            "git",
            "-C",
            str(seed),
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@test",
            "commit",
            "--quiet",
            "-m",
            "seed",
        ),
        check=True,
    )
    subprocess.run(("git", "-C", str(seed), "push", "--quiet", "origin", "HEAD"), check=True)
    return tmp_path / "remote"


@pytest.fixture
def workspace(remote: Path, tmp_path: Path) -> WorkspaceAdapter:
    """An adapter cloning anonymously from the local bare remote."""
    return WorkspaceAdapter(tmp_path / "work", str(remote / "{slug}.git"), None, timedelta(minutes=1))


@pytest.fixture
def client() -> Iterator[wreq.Client]:
    client = wreq.Client()
    yield client
    client.close()


@pytest.fixture
def base(httpserver: HTTPServer) -> str:
    return httpserver.url_for("").rstrip("/")


@pytest.fixture
def github(client: wreq.Client, base: str) -> GithubAdapter:
    return GithubAdapter(client, base, "secret-token", AGENT)


@pytest.fixture
def anonymous_github(client: wreq.Client, base: str) -> GithubAdapter:
    return GithubAdapter(client, base, None, AGENT)


@pytest.fixture
def pypi(client: wreq.Client, base: str) -> PypiAdapter:
    return PypiAdapter(client, base, AGENT)


@pytest.fixture
def crates(client: wreq.Client, base: str) -> CratesAdapter:
    return CratesAdapter(client, base, AGENT)


@pytest.fixture
def osv(client: wreq.Client, base: str) -> OsvAdapter:
    return OsvAdapter(client, base, AGENT)
