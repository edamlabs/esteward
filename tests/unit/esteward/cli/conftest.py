"""The CLI wired against one local server standing in for GitHub, PyPI and OSV."""

from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from esteward.core.settings import Settings

SHA = "c" * 40
ENTRY = """
repo = "edamlabs/project"
kind = "lib"
modules = ["deps", "security"]

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
        {"archived": False, "pushed_at": "2026-10-01T00:00:00Z"}
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
    httpserver.expect_request("/repos/edamlabs/project/issues", method="GET").respond_with_json([])
    httpserver.expect_request("/repos/edamlabs/project/issues", method="POST").respond_with_json({}, status=201)
    return httpserver
