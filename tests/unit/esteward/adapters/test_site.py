"""The site adapter on the wire: statuses, page texts, absence as None."""

import pytest
import wreq
from pytest_httpserver import HTTPServer

from esteward.adapters.site import SiteAdapter


@pytest.fixture
def site_adapter(client: wreq.Client, base: str) -> SiteAdapter:
    return SiteAdapter(client, "esteward-test")


async def test_status(httpserver: HTTPServer, site_adapter: SiteAdapter) -> None:
    httpserver.expect_request("/x").respond_with_data("", status=404)
    httpserver.expect_request("/y").respond_with_data("ok")
    assert await site_adapter.status(httpserver.url_for("/x")) == 404
    assert await site_adapter.status(httpserver.url_for("/y")) == 200


async def test_text(httpserver: HTTPServer, site_adapter: SiteAdapter) -> None:
    httpserver.expect_request("/page").respond_with_data("hello")
    httpserver.expect_request("/gone").respond_with_data("", status=410)
    assert await site_adapter.text(httpserver.url_for("/page")) == "hello"
    assert await site_adapter.text(httpserver.url_for("/gone")) is None


async def test_text_server_error(httpserver: HTTPServer, site_adapter: SiteAdapter) -> None:
    httpserver.expect_request("/boom").respond_with_data("boom", status=500)
    with pytest.raises(wreq.StatusError):
        await site_adapter.text(httpserver.url_for("/boom"))
