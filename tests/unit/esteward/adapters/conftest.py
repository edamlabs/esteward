"""A real HTTP client against a local server: adapters are tested on the wire, no mocks."""

from collections.abc import Iterator

import pytest
import wreq
from pytest_httpserver import HTTPServer

from esteward.adapters.crates import CratesAdapter
from esteward.adapters.github import GithubAdapter
from esteward.adapters.osv import OsvAdapter
from esteward.adapters.pypi import PypiAdapter

AGENT = "esteward-test"


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
