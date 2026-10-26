"""The act stage end to end: a vulnerable lockfile in a bare remote, a fake uv on PATH, a tracker on the wire."""

import json
import subprocess
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.cli.commands import run as run_command
from esteward.core.settings import Settings
from esteward.models.fleet import ModuleFleet
from tests.unit.esteward.cli.conftest import BRANCH


@pytest.fixture(autouse=True)
def local(monkeypatch: pytest.MonkeyPatch, act_settings: Settings) -> None:
    monkeypatch.setattr(run_command, "st", act_settings)


def heads(origin: Path) -> str:
    """The branches of the bare remote."""
    done = subprocess.run(
        ("git", "-C", str(origin / "edamlabs" / "project.git"), "for-each-ref", "refs/heads"),
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def test_run_act_publish(
    act_world: HTTPServer, origin: Path, fake_uv: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_command.run("project", module=(ModuleFleet.DEPS,), act=True, publish=True, report_dir=tmp_path / "reports")
    assert f"refs/heads/{BRANCH}" in heads(origin)
    created = [
        request.get_json()
        for request, _ in act_world.log
        if request.method == "POST" and request.path.endswith("/pulls")
    ]
    assert [(pull["head"], pull["base"], pull["title"]) for pull in created] == [
        (BRANCH, "main", "fix(deps): urllib3 1.26.0 → 2.5.0")
    ]
    graphql = [request.get_json() for request, _ in act_world.log if request.path == "/graphql"]
    assert graphql
    assert "enablePullRequestAutoMerge" in graphql[0]["query"]
    (report,) = [json.loads(path.read_bytes()) for path in (tmp_path / "reports").glob("*.json")]
    (finding,) = [found for found in report["findings"] if found["key"].startswith("deps:advisory")]
    assert finding["verdict"] == "act"
    assert finding["detail"].endswith("[PR #5](https://gh/edamlabs/project/pull/5)")
    dashboard = next(
        request.get_json()
        for request, _ in act_world.log
        if request.method == "POST"
        and request.path.endswith("/issues")
        and request.get_json()["labels"] == ["esteward"]
    )
    assert "[PR #5](https://gh/edamlabs/project/pull/5)" in dashboard["body"]
    assert "edamlabs/project" in capsys.readouterr().out


def test_run_act_dry(act_world: HTTPServer, origin: Path, fake_uv: None, tmp_path: Path) -> None:
    run_command.run("project", module=(ModuleFleet.DEPS,), act=True, report_dir=tmp_path / "reports")
    assert f"refs/heads/{BRANCH}" not in heads(origin)
    assert not [request for request, _ in act_world.log if request.path.endswith("/pulls")]
    assert not [
        request for request, _ in act_world.log if request.method == "POST" and request.path.endswith("/issues")
    ]
    (report,) = [json.loads(path.read_bytes()) for path in (tmp_path / "reports").glob("*.json")]
    (finding,) = [found for found in report["findings"] if found["key"].startswith("deps:advisory")]
    assert finding["verdict"] == "act"
    assert finding["detail"].endswith("bump verified (dry run)")
