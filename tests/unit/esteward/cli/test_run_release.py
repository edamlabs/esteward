"""The release stage end to end: a due fix folds into a self-merging release PR."""

import subprocess
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.cli.commands import run as run_command
from esteward.core.settings import Settings
from esteward.models.fleet import ModuleFleet
from tests.unit.esteward.cli.conftest import RELEASE_BRANCH, heads


@pytest.fixture(autouse=True)
def local(monkeypatch: pytest.MonkeyPatch, release_settings: Settings) -> None:
    monkeypatch.setattr(run_command, "st", release_settings)


def test_run_release_publish(release_world: HTTPServer, release_origin: Path) -> None:
    run_command.run("project", module=(ModuleFleet.RELEASE,), release=True, publish=True)
    assert f"refs/heads/{RELEASE_BRANCH}" in heads(release_origin)
    created = [
        request.get_json()
        for request, _ in release_world.log
        if request.method == "POST" and request.path.endswith("/pulls")
    ]
    assert [(pull["head"], pull["base"], pull["title"]) for pull in created] == [
        (RELEASE_BRANCH, "main", "chore(release): v0.1.1")
    ]
    graphql = [request.get_json() for request, _ in release_world.log if request.path == "/graphql"]
    assert graphql
    assert "enablePullRequestAutoMerge" in graphql[0]["query"]
    folded = subprocess.run(
        ("git", "-C", str(release_origin / "edamlabs" / "project.git"), "show", f"{RELEASE_BRANCH}:CHANGELOG.md"),
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "## [Unreleased]\n\n## [0.1.1] — " in folded
    assert "- A real bug." in folded


def test_run_release_dry(release_world: HTTPServer, release_origin: Path) -> None:
    run_command.run("project", module=(ModuleFleet.RELEASE,), release=True)
    assert f"refs/heads/{RELEASE_BRANCH}" not in heads(release_origin)
    assert not [request for request, _ in release_world.log if request.path.endswith("/pulls")]
    assert not [
        request for request, _ in release_world.log if request.method == "POST" and request.path.endswith("/issues")
    ]
