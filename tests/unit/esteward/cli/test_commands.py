"""The commands end to end: fleet listing, dry runs and published runs."""

import json
import runpy
import sys
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.cli.commands import fleet as fleet_command
from esteward.cli.commands import run as run_command
from esteward.cli.main import main
from esteward.core.settings import Settings
from esteward.models.fleet import ModuleFleet


@pytest.fixture(autouse=True)
def local(monkeypatch: pytest.MonkeyPatch, local_settings: Settings) -> None:
    monkeypatch.setattr(fleet_command, "st", local_settings)
    monkeypatch.setattr(run_command, "st", local_settings)


async def test_fleet(capsys: pytest.CaptureFixture[str]) -> None:
    fleet_command.fleet()
    assert json.loads(capsys.readouterr().out) == ["project"]


def test_run_dry(world: HTTPServer, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_command.run("project", report_dir=tmp_path / "reports")
    reports = {path.stem: json.loads(path.read_bytes()) for path in (tmp_path / "reports").glob("*.json")}
    assert {name: [f["verdict"] for f in r["findings"]] for name, r in reports.items()} == {
        "deps": ["ok", "escalate"],
        "security": ["escalate"],
    }
    assert not [request for request, _ in world.log if request.method == "POST" and request.path.endswith("/issues")]
    assert "edamlabs/project" in capsys.readouterr().out


def test_run_publish(world: HTTPServer) -> None:
    run_command.run("project", module=(ModuleFleet.SECURITY,), publish=True)
    created = [
        request.get_json() for request, _ in world.log if request.method == "POST" and request.path.endswith("/issues")
    ]
    assert sorted(issue["labels"][0] for issue in created) == ["esteward", "esteward-escalation"]
    assert not [request for request, _ in world.log if request.path.startswith("/querybatch")]


def test_main(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["esteward", "fleet"])
    with pytest.raises(SystemExit) as exited:
        main()
    assert exited.value.code == 0
    assert json.loads(capsys.readouterr().out) == ["project"]


def test_module_entry(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["esteward", "fleet"])
    with pytest.raises(SystemExit):
        runpy.run_module("esteward", run_name="__main__")
    assert json.loads(capsys.readouterr().out) == ["project"]
