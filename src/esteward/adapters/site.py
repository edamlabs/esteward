"""A deployed documentation site, probed over HTTP."""

from http import HTTPStatus

import wreq


class SiteAdapter:
    """One HTTP client for documentation sites: statuses and page texts, absence as None."""

    __slots__ = ("_client", "_headers")

    def __init__(self, client: wreq.Client, user_agent: str) -> None:
        self._client = client
        self._headers = {"User-Agent": user_agent}

    ##### PUBLIC #####

    async def status(self, url: str) -> int:
        """The final status of one URL, redirects followed."""
        response = await self._client.get(url, headers=self._headers)
        return response.status.as_int()

    async def text(self, url: str) -> str | None:
        """One page as text; None when the site answers 404 or 410."""
        response = await self._client.get(url, headers=self._headers)
        match response.status.as_int():
            case HTTPStatus.NOT_FOUND | HTTPStatus.GONE:
                return None
            case _:
                response.raise_for_status()
                return await response.text()
