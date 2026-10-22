"""URL parts the modules address things by."""

import pytest

from esteward.logic.url import host_url, name_url, slug_url


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
    assert (slug_url(url), host_url(url), name_url(url)) == (slug, host, name)
