"""One URL parsed once: the repository slug, the registry host, the package name."""

import pytest

from esteward.ops.url import Url


@pytest.mark.parametrize(
    ("url", "slug", "host", "name"),
    [
        ("https://github.com/edamlabs/esteward", "edamlabs/esteward", "github.com", "esteward"),
        ("https://github.com/owner/repo/tree/main", "owner/repo", "github.com", "main"),
        ("https://www.pypi.org/project/lxml/", "project/lxml", "pypi.org", "lxml"),
        ("https://crates.io/crates/pyo3", "crates/pyo3", "crates.io", "pyo3"),
    ],
    ids=["repo", "repo-subpath", "pypi", "crates"],
)
async def test_url_parts(url: str, slug: str, host: str, name: str) -> None:
    parsed = Url(url)
    assert (parsed.slug(), parsed.host(), parsed.name()) == (slug, host, name)
