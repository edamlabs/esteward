"""PyPI and crates.io adapters on the wire."""

from datetime import UTC, datetime

import pytest
from pytest_httpserver import HTTPServer

from esteward.adapters.crates import CratesAdapter
from esteward.adapters.pypi import PypiAdapter
from esteward.models.signal import PackageSignal

RELEASE = {
    "info": {"version": "6.1.3", "license_expression": None, "license": "BSD-3-Clause", "yanked": False},
    "urls": [{"upload_time_iso_8601": "2026-09-02T14:50:00Z"}, {"upload_time_iso_8601": "2026-09-02T14:46:05Z"}],
    "releases": {"6.1.3": [{"yanked": False}], "7.0.0rc1": [{"yanked": False}]},
}


async def test_pypi_package(httpserver: HTTPServer, pypi: PypiAdapter) -> None:
    httpserver.expect_request("/pypi/lxml/json").respond_with_json(RELEASE)
    httpserver.expect_request(
        "/simple/lxml/", headers={"Accept": "application/vnd.pypi.simple.v1+json"}
    ).respond_with_json({"project-status": {"status": "archived"}})
    assert await pypi.package("lxml") == PackageSignal(
        "lxml",
        "6.1.3",
        datetime(2026, 9, 2, 14, 46, 5, tzinfo=UTC),
        "archived",
        "BSD-3-Clause",
        yanked=False,
        newest="7.0.0rc1",
    )


@pytest.mark.parametrize(
    ("simple", "status"),
    [(None, "active"), ({"meta": {}}, "active"), ({"project-status": None}, "active")],
    ids=["no-simple-page", "no-marker", "null-marker"],
)
async def test_pypi_status_default(httpserver: HTTPServer, pypi: PypiAdapter, simple: dict | None, status: str) -> None:
    httpserver.expect_request("/pypi/x/json").respond_with_json(
        {"info": {"version": "1", "license_expression": "MIT"}, "urls": [], "releases": {"1": [{"yanked": False}]}}
    )
    match simple:
        case None:
            httpserver.expect_request("/simple/x/").respond_with_data("", status=404)
        case payload:
            httpserver.expect_request("/simple/x/").respond_with_json(payload)
    signal = await pypi.package("x")
    assert signal is not None
    assert (signal.status, signal.license, signal.released_at, signal.yanked) == (status, "MIT", None, False)


async def test_pypi_absent(httpserver: HTTPServer, pypi: PypiAdapter) -> None:
    httpserver.expect_request("/pypi/x/json").respond_with_data("", status=404)
    httpserver.expect_request("/simple/x/").respond_with_data("", status=404)
    assert await pypi.package("x") is None


async def test_pypi_newest_all_yanked(httpserver: HTTPServer, pypi: PypiAdapter) -> None:
    """A project whose every release is yanked still names its newest: the upstream row must not crash."""
    httpserver.expect_request("/pypi/x/json").respond_with_json(
        {"info": {"version": "1", "license_expression": "MIT"}, "urls": [], "releases": {"1": [{"yanked": True}]}}
    )
    httpserver.expect_request("/simple/x/").respond_with_json({})
    signal = await pypi.package("x")
    assert signal is not None
    assert signal.newest == "1"


async def test_pypi_unexpected(httpserver: HTTPServer, pypi: PypiAdapter) -> None:
    httpserver.expect_request("/pypi/x/json").respond_with_json({"oops": 1})
    httpserver.expect_request("/simple/x/").respond_with_json({})
    with pytest.raises(ValueError, match="unexpected PyPI JSON"):
        await pypi.package("x")


@pytest.mark.parametrize(
    ("stable", "version"), [("0.30.1", "0.30.1"), (None, "0.31.0-rc1")], ids=["stable", "prerelease-only"]
)
async def test_crates_package(httpserver: HTTPServer, crates: CratesAdapter, stable: str | None, version: str) -> None:
    httpserver.expect_request("/crates/pyo3", headers={"User-Agent": "esteward-test"}).respond_with_json(
        {
            "crate": {"max_stable_version": stable, "newest_version": "0.31.0-rc1"},
            "versions": [
                {"num": "0.31.0-rc1", "created_at": "2026-10-20T00:00:00Z", "yanked": True, "license": "MIT"},
                {
                    "num": "0.30.1",
                    "created_at": "2026-10-14T21:19:37Z",
                    "yanked": False,
                    "license": "MIT OR Apache-2.0",
                },
            ],
        }
    )
    signal = await crates.package("pyo3")
    assert signal is not None
    assert (signal.version, signal.status) == (version, "active")


async def test_crates_absent(httpserver: HTTPServer, crates: CratesAdapter) -> None:
    httpserver.expect_request("/crates/x").respond_with_data("", status=404)
    assert await crates.package("x") is None
