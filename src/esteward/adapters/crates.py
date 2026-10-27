"""crates.io: the latest stable release of a crate; crates.io has no project status markers, every crate is active."""

from datetime import datetime
from http import HTTPStatus

import wreq

from esteward.models.signal import PackageSignal


class CratesAdapter:
    """One crates.io client; its API refuses requests without a User-Agent."""

    __slots__ = ("_api", "_client", "_headers")

    def __init__(self, client: wreq.Client, api: str, user_agent: str) -> None:
        self._client = client
        self._api = api.rstrip("/")
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}

    async def package(self, name: str) -> PackageSignal | None:
        """The latest stable version, its publication time, license and yanked flag; None when the crate is unknown."""
        response = await self._client.get(f"{self._api}/crates/{name}", headers=self._headers)
        match response.status.as_int():
            case HTTPStatus.NOT_FOUND:
                return None
            case _:
                response.raise_for_status()
        data = await response.json()
        version = data["crate"].get("max_stable_version") or data["crate"]["newest_version"]
        entry = next(item for item in data["versions"] if item["num"] == version)
        return PackageSignal(
            name=name,
            version=version,
            released_at=datetime.fromisoformat(entry["created_at"]),
            status="active",
            license=entry.get("license"),
            yanked=bool(entry["yanked"]),
            newest=data["crate"]["newest_version"],
        )
