"""The CLI wired against one local server standing in for GitHub, PyPI and OSV."""

import os
import subprocess
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.core.settings import Settings

SHA = "c" * 40
BRANCH = "esteward/act/deps-advisory-vulnerability-urllib3-1-26-0"
PULL = {
    "number": 5,
    "node_id": "PR5",
    "head": {"ref": BRANCH},
    "body": "b",
    "auto_merge": {"merge_method": "squash"},
    "html_url": "https://gh/edamlabs/project/pull/5",
}
RELEASE_BRANCH = "esteward/release/v0.1.1"
RELEASE_PULL = {
    "number": 9,
    "node_id": "PR9",
    "head": {"ref": RELEASE_BRANCH},
    "body": "b",
    "auto_merge": {"merge_method": "squash"},
    "html_url": "https://gh/edamlabs/project/pull/9",
}
CHANGELOG = """# Changelog

## [Unreleased]

### Fixed

- A real bug.

## [0.1.0] — 2026-10-01

First release.
"""
ENTRY = """
repo = "edamlabs/project"
kind = "lib"
family = "binding"
modules = ["deps", "security", "drift"]

[deps]
lockfiles = ["uv.lock"]

[[deps.watch]]
name = "dep"
repo = "https://github.com/owner/dep"
registry = "https://pypi.org/project/dep/"
license = "MIT"
"""


@pytest.fixture
def fleet_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "fleet"
    directory.mkdir()
    (directory / "project.toml").write_text(ENTRY, encoding="utf-8")
    return directory


def heads(remote: Path) -> str:
    """The branches of the bare remote."""
    done = subprocess.run(
        ("git", "-C", str(remote / "edamlabs" / "project.git"), "for-each-ref", "refs/heads"),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


@pytest.fixture
def local_settings(httpserver: HTTPServer, fleet_dir: Path) -> Settings:
    base = httpserver.url_for("").rstrip("/")
    return Settings(
        github_api=base, pypi_url=base, crates_api=base, osv_api=base, fleet_dir=fleet_dir, github_token=None
    )


@pytest.fixture
def world(httpserver: HTTPServer, resources: Path) -> HTTPServer:
    """A healthy dependency, one vulnerable locked package, one phantom pin, no issue yet."""
    httpserver.expect_request("/repos/owner/dep").respond_with_json(
        {"full_name": "owner/dep", "archived": False, "pushed_at": "2026-10-01T00:00:00Z"}
    )
    httpserver.expect_request("/pypi/dep/json").respond_with_json(
        {
            "info": {"version": "1.0", "license_expression": "MIT"},
            "urls": [{"upload_time_iso_8601": "2026-10-01T00:00:00Z"}],
        }
    )
    httpserver.expect_request("/simple/dep/").respond_with_json({"project-status": {"status": "active"}})
    httpserver.expect_request("/repos/edamlabs/project/contents/uv.lock").respond_with_data(
        (resources / "uv.lock").read_text(encoding="utf-8")
    )
    httpserver.expect_request("/querybatch", method="POST").respond_with_json(
        {"results": [{"vulns": [{"id": "GHSA-1"}]}]}
    )
    httpserver.expect_request("/vulns/GHSA-1").respond_with_json(
        {"id": "GHSA-1", "summary": "bomb", "affected": [{"package": {"name": "urllib3", "ecosystem": "PyPI"}}]}
    )
    httpserver.expect_request("/repos/edamlabs/project/git/trees/HEAD").respond_with_json(
        {"tree": [{"path": ".github/workflows/ci.yml", "type": "blob"}]}
    )
    httpserver.expect_request("/repos/edamlabs/project/contents/.github/workflows/ci.yml").respond_with_data(
        f"steps:\n  - uses: owner/action@{SHA}\n"
    )
    httpserver.expect_request(f"/repos/owner/action/commits/{SHA}").respond_with_data("", status=422)
    httpserver.expect_request("/repos/edamlabs/project/contents/pyproject.toml").respond_with_data(
        '[tool.edamlabs]\nkind = "lib"\nfamily = "binding"\n'
    )
    httpserver.expect_request("/repos/edamlabs/project/contents/Cargo.toml").respond_with_data("", status=404)
    httpserver.expect_request("/repos/edamlabs/project/issues", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/issues", method="POST").respond_with_json({}, status=201)
    return httpserver


@pytest.fixture
def origin(tmp_path: Path, resources: Path) -> Path:
    """A bare remote holding the project: the vulnerable uv.lock of the resource tree, committed on main."""
    bare = tmp_path / "origin" / "edamlabs" / "project.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(("git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)), check=True)
    seed = tmp_path / "seed"
    subprocess.run(("git", "clone", "--quiet", str(bare), str(seed)), check=True)
    (seed / "uv.lock").write_text((resources / "uv.lock").read_text(encoding="utf-8"), encoding="utf-8")
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
    return tmp_path / "origin"


@pytest.fixture
def fake_uv(tmp_path: Path, resources: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A `uv` on PATH that does the one thing the act stage asks of it: write the fixed lock."""
    binary = tmp_path / "bin"
    binary.mkdir()
    script = binary / "uv"
    script.write_text(f'#!/bin/sh\ncp "{resources / "uv-fixed.lock"}" uv.lock\n', encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{binary}{os.pathsep}{os.environ['PATH']}")


@pytest.fixture
def act_settings(httpserver: HTTPServer, fleet_dir: Path, origin: Path, tmp_path: Path) -> Settings:
    """Settings cloning from the local bare remote into a throwaway workspace."""
    base = httpserver.url_for("").rstrip("/")
    return Settings(
        github_api=base,
        pypi_url=base,
        crates_api=base,
        osv_api=base,
        fleet_dir=fleet_dir,
        github_token=None,
        work_dir=tmp_path / "work",
        git_remote=str(origin / "{slug}.git"),
    )


@pytest.fixture
def act_world(httpserver: HTTPServer, resources: Path) -> HTTPServer:
    """The world of an act run: one fixable vulnerability, a tracker answering pulls and GraphQL."""
    httpserver.expect_request("/repos/edamlabs/project").respond_with_json(
        {
            "full_name": "edamlabs/project",
            "archived": False,
            "pushed_at": "2026-10-01T00:00:00Z",
            "default_branch": "main",
        }
    )
    httpserver.expect_request("/repos/owner/dep").respond_with_json(
        {"full_name": "owner/dep", "archived": False, "pushed_at": "2026-10-01T00:00:00Z"}
    )
    httpserver.expect_request("/pypi/dep/json").respond_with_json(
        {
            "info": {"version": "1.0", "license_expression": "MIT"},
            "urls": [{"upload_time_iso_8601": "2026-10-01T00:00:00Z"}],
        }
    )
    httpserver.expect_request("/simple/dep/").respond_with_json({"project-status": {"status": "active"}})
    httpserver.expect_request("/repos/edamlabs/project/contents/uv.lock").respond_with_data(
        (resources / "uv.lock").read_text(encoding="utf-8")
    )
    httpserver.expect_request("/querybatch", method="POST").respond_with_json(
        {"results": [{"vulns": [{"id": "GHSA-1"}]}]}
    )
    httpserver.expect_request("/vulns/GHSA-1").respond_with_json(
        {
            "id": "GHSA-1",
            "summary": "bomb",
            "affected": [
                {
                    "package": {"name": "urllib3", "ecosystem": "PyPI"},
                    "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.5.0"}]}],
                }
            ],
        }
    )
    httpserver.expect_request("/repos/edamlabs/project/issues", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/issues", method="POST").respond_with_json({}, status=201)
    httpserver.expect_oneshot_request("/repos/edamlabs/project/pulls", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/pulls", method="GET").respond_with_json([PULL])
    httpserver.expect_request("/repos/edamlabs/project/pulls", method="POST").respond_with_json(PULL, status=201)
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"enablePullRequestAutoMerge": {"clientMutationId": "1"}}}
    )
    return httpserver


@pytest.fixture
def release_fleet_dir(tmp_path: Path) -> Path:
    """A fleet directory whose single entry enables only the release module."""
    directory = tmp_path / "fleet"
    directory.mkdir()
    (directory / "project.toml").write_text(
        'repo = "edamlabs/project"\nkind = "lib"\nfamily = "binding"\nmodules = ["release"]\n', encoding="utf-8"
    )
    return directory


@pytest.fixture
def release_origin(tmp_path: Path) -> Path:
    """A bare remote holding the project's changelog: no manifest, so the fold needs no solver."""
    bare = tmp_path / "origin" / "edamlabs" / "project.git"
    bare.parent.mkdir(parents=True)
    subprocess.run(("git", "init", "--quiet", "--bare", "--initial-branch=main", str(bare)), check=True)
    seed = tmp_path / "seed"
    subprocess.run(("git", "clone", "--quiet", str(bare), str(seed)), check=True)
    (seed / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
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
    return tmp_path / "origin"


@pytest.fixture
def release_settings(httpserver: HTTPServer, release_fleet_dir: Path, release_origin: Path, tmp_path: Path) -> Settings:
    base = httpserver.url_for("").rstrip("/")
    return Settings(
        github_api=base,
        pypi_url=base,
        crates_api=base,
        osv_api=base,
        fleet_dir=release_fleet_dir,
        github_token=None,
        work_dir=tmp_path / "work",
        git_remote=str(release_origin / "{slug}.git"),
    )


@pytest.fixture
def release_world(httpserver: HTTPServer) -> HTTPServer:
    """The world of a release run: one due fix, one tag behind it, a tracker answering pulls and GraphQL."""
    httpserver.expect_request("/repos/edamlabs/project").respond_with_json(
        {
            "full_name": "edamlabs/project",
            "archived": False,
            "pushed_at": "2026-10-01T00:00:00Z",
            "default_branch": "main",
        }
    )
    httpserver.expect_request("/repos/edamlabs/project/contents/CHANGELOG.md").respond_with_data(CHANGELOG)
    httpserver.expect_request("/repos/edamlabs/project/git/matching-refs/tags/v").respond_with_json(
        [{"ref": "refs/tags/v0.1.0"}]
    )
    httpserver.expect_request("/repos/edamlabs/project/compare/v0.1.0...HEAD").respond_with_json(
        {"commits": [{"commit": {"message": "fix: a real bug", "committer": {"date": "2026-10-21T00:00:00Z"}}}]}
    )
    httpserver.expect_request("/repos/edamlabs/project/issues", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/issues", method="POST").respond_with_json({}, status=201)
    httpserver.expect_oneshot_request("/repos/edamlabs/project/pulls", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/pulls", method="GET").respond_with_json([RELEASE_PULL])
    httpserver.expect_request("/repos/edamlabs/project/pulls", method="POST").respond_with_json(
        RELEASE_PULL, status=201
    )
    httpserver.expect_request("/graphql", method="POST").respond_with_json(
        {"data": {"enablePullRequestAutoMerge": {"clientMutationId": "1"}}}
    )
    return httpserver
