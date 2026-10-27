"""PyPI: the latest release from the JSON API and the PEP 792 project status from the simple index."""

import asyncio
from datetime import datetime
from http import HTTPStatus
from typing import Any, Final

import wreq
from packaging.version import Version

from esteward.models.signal import PackageSignal

SIMPLE_JSON: Final = "application/vnd.pypi.simple.v1+json"


class PypiAdapter:
    """One PyPI client: release metadata and project status of a package; None when the project does not exist."""

    __slots__ = ("_client", "_headers", "_url")

    def __init__(self, client: wreq.Client, url: str, user_agent: str) -> None:
        self._client = client
        self._url = url.rstrip("/")
        self._headers = {"User-Agent": user_agent}

    ##### PRIVATE #####

    async def _package_json(self, path: str, accept: str = "application/json") -> dict[str, Any] | None:
        """A JSON document of the index; None on 404."""
        response = await self._client.get(f"{self._url}{path}", headers=self._headers | {"Accept": accept})
        match response.status.as_int():
            case HTTPStatus.NOT_FOUND:
                return None
            case _:
                response.raise_for_status()
                return await response.json()

    @staticmethod
    def _package_newest(release: dict[str, Any]) -> str:
        """The newest release of any kind, prereleases included; yanked versions only when all are."""
        releases = release.get("releases", {})
        live = [version for version, files in releases.items() if any(not file.get("yanked") for file in files)]
        versions = live or list(releases)
        return max(versions, key=Version) if versions else release["info"]["version"]

    ############################################################

    ##### PUBLIC #####

    async def package(self, name: str) -> PackageSignal | None:
        """The latest release, its upload time, license, yanked flag and the project's PEP 792 status."""
        release, simple = await asyncio.gather(
            self._package_json(f"/pypi/{name}/json"), self._package_json(f"/simple/{name}/", SIMPLE_JSON)
        )
        match release:
            case None:
                return None
            case {"info": info, "urls": files} as release:
                uploads = [entry["upload_time_iso_8601"] for entry in files]
                return PackageSignal(
                    name=name,
                    version=info["version"],
                    released_at=datetime.fromisoformat(min(uploads)) if uploads else None,
                    status=((simple or {}).get("project-status") or {}).get("status", "active"),
                    license=info.get("license_expression") or info.get("license") or None,
                    yanked=bool(info.get("yanked")),
                    newest=PypiAdapter._package_newest(release),
                )
            case other:
                message = f"unexpected PyPI JSON for {name}: keys {sorted(other)}"
                raise ValueError(message)
