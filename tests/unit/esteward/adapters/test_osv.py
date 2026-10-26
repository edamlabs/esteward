"""OSV adapter on the wire: batch ids, one detail per advisory, kinds and fixes read as OSV publishes them."""

import pytest
from pytest_httpserver import HTTPServer

from esteward.adapters.osv import OsvAdapter
from esteward.models.package import AdvisoryPackage, EcosystemPackage, KindPackage, LockedPackage

URLLIB3 = LockedPackage(EcosystemPackage.PYPI, "urllib3", "1.26.0")
ATTY = LockedPackage(EcosystemPackage.CRATES, "atty", "0.2.14")


async def test_advisories(httpserver: HTTPServer, osv: OsvAdapter) -> None:
    httpserver.expect_request("/querybatch", method="POST").respond_with_json(
        {"results": [{"vulns": [{"id": "GHSA-1"}, {"id": "GHSA-old"}]}, {"vulns": [{"id": "RUSTSEC-1"}]}]}
    )
    httpserver.expect_request("/vulns/GHSA-1").respond_with_json(
        {
            "id": "GHSA-1",
            "summary": "decompression bomb",
            "affected": [
                {"package": {"name": "other", "ecosystem": "PyPI"}, "ranges": [{"events": [{"fixed": "9"}]}]},
                {
                    "package": {"name": "urllib3", "ecosystem": "PyPI"},
                    "ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.6.0"}]}],
                },
            ],
        }
    )
    httpserver.expect_request("/vulns/GHSA-old").respond_with_json(
        {"id": "GHSA-old", "withdrawn": "2025-01-01T00:00:00Z"}
    )
    httpserver.expect_request("/vulns/RUSTSEC-1").respond_with_json(
        {
            "id": "RUSTSEC-1",
            "details": "atty is unmaintained, use std::io::IsTerminal",
            "affected": [
                {
                    "package": {"name": "atty", "ecosystem": "crates.io"},
                    "database_specific": {"informational": "unmaintained"},
                }
            ],
        }
    )
    assert await osv.advisories((URLLIB3, ATTY)) == (
        AdvisoryPackage("GHSA-1", URLLIB3, KindPackage.VULNERABILITY, "decompression bomb", "2.6.0"),
        AdvisoryPackage(
            "RUSTSEC-1", ATTY, KindPackage.UNMAINTAINED, "atty is unmaintained, use std::io::IsTerminal", None
        ),
    )
    assert httpserver.log[0][0].get_json() == {
        "queries": [
            {"package": {"name": "urllib3", "ecosystem": "PyPI"}, "version": "1.26.0"},
            {"package": {"name": "atty", "ecosystem": "crates.io"}, "version": "0.2.14"},
        ]
    }


async def test_advisories_summary_fallback(httpserver: HTTPServer, osv: OsvAdapter) -> None:
    httpserver.expect_request("/querybatch", method="POST").respond_with_json({"results": [{"vulns": [{"id": "X-1"}]}]})
    httpserver.expect_request("/vulns/X-1").respond_with_json({"id": "X-1"})
    (advisory,) = await osv.advisories((URLLIB3,))
    assert (advisory.summary, advisory.fixed, advisory.kind) == ("X-1", None, KindPackage.VULNERABILITY)


async def test_advisories_none(httpserver: HTTPServer, osv: OsvAdapter) -> None:
    httpserver.expect_request("/querybatch", method="POST").respond_with_json({"results": [{}]})
    assert await osv.advisories((URLLIB3,)) == ()
    assert await osv.advisories(()) == ()


@pytest.mark.parametrize(
    ("version", "events", "fixed"),
    [
        (
            "1.0.9",
            [{"introduced": "0.0.0-0"}, {"fixed": "0.26.11"}, {"introduced": "0.26.12-0"}, {"fixed": "1.0.10"}],
            "1.0.10",
        ),
        (
            "0.26.12",
            [{"introduced": "0.0.0-0"}, {"fixed": "0.26.11"}, {"introduced": "0.26.12-0"}, {"fixed": "1.0.10"}],
            "1.0.10",
        ),
        ("3.0.0", [{"introduced": "0"}, {"fixed": "2.0.0"}, {"introduced": "3.0.0"}], None),
        ("not-a-version", [{"introduced": "0"}, {"fixed": "2.0.0"}], "2.0.0"),
        ("1.0.0", [{"introduced": "0"}, {"last_affected": "1.5.0"}], None),
    ],
    ids=["second-branch", "semver-lowest-prerelease", "open-interval", "unparsable", "last-affected"],
)
async def test_advisories_fixed_branch(
    httpserver: HTTPServer, osv: OsvAdapter, version: str, events: list[dict[str, str]], fixed: str | None
) -> None:
    locked = LockedPackage(EcosystemPackage.CRATES, "webpki-roots", version)
    httpserver.expect_request("/querybatch", method="POST").respond_with_json({"results": [{"vulns": [{"id": "R-1"}]}]})
    httpserver.expect_request("/vulns/R-1").respond_with_json(
        {
            "id": "R-1",
            "affected": [
                {"package": {"name": "webpki-roots", "ecosystem": "crates.io"}, "ranges": [{"events": events}]}
            ],
        }
    )
    (advisory,) = await osv.advisories((locked,))
    assert advisory.fixed == fixed
