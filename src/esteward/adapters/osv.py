"""OSV: advisories against exact package versions, RustSec's unmaintained notices included."""

import asyncio
from itertools import batched
from typing import Any, Final

import wreq
from packaging.version import InvalidVersion, Version

from esteward.models.package import AdvisoryPackage, KindPackage, LockedPackage

BATCH: Final = 1000


class OsvAdapter:
    """One OSV client: a batch query for ids, then one detail fetch per distinct advisory."""

    __slots__ = ("_api", "_client", "_headers", "_limit")

    def __init__(self, client: wreq.Client, api: str, user_agent: str, concurrency: int = 8) -> None:
        self._client = client
        self._api = api.rstrip("/")
        self._headers = {"User-Agent": user_agent}
        self._limit = asyncio.Semaphore(concurrency)

    ##### PRIVATE #####

    async def _advisories_chunk(self, chunk: tuple[LockedPackage, ...]) -> list[tuple[LockedPackage, str]]:
        """`(package, advisory id)` for one querybatch of at most BATCH packages."""
        queries = [{"package": {"name": p.name, "ecosystem": p.ecosystem}, "version": p.version} for p in chunk]
        response = await self._client.post(f"{self._api}/querybatch", headers=self._headers, json={"queries": queries})
        response.raise_for_status()
        results = (await response.json())["results"]
        return [
            (package, vuln["id"])
            for package, result in zip(chunk, results, strict=True)
            for vuln in result.get("vulns", ())
        ]

    async def _advisories_detail(self, advisory_id: str) -> dict[str, Any]:
        async with self._limit:
            response = await self._client.get(f"{self._api}/vulns/{advisory_id}", headers=self._headers)
            response.raise_for_status()
            return await response.json()

    @staticmethod
    def _advisories_version(text: str) -> Version | None:
        """An OSV version as comparable; semver's `-0` (lowest prerelease) is the version itself; None if unparsable."""
        try:
            return Version(text.removesuffix("-0"))
        except InvalidVersion:
            return None

    @staticmethod
    def _advisories_intervals(span: dict[str, Any]) -> list[tuple[str, str]]:
        """The closed `(introduced, fixed)` intervals of one OSV range; a trailing `introduced` is open, unfixed."""
        events = [(kind, value) for event in span.get("events", ()) for kind, value in event.items()]
        return [
            (start, end)
            for (opened, start), (closed, end) in zip(events[::2], events[1::2], strict=False)
            if (opened, closed) == ("introduced", "fixed")
        ]

    @staticmethod
    def _advisories_fixed(locked: str, spans: list[dict[str, Any]]) -> str | None:
        """The fix of the interval `introduced <= locked < fixed` that holds the locked version, None if unfixed.

        OSV ranges alternate `introduced` and `fixed` events, one interval per release branch; the fix of another
        branch is not a fix for this one. An unparsable locked version falls back to the first fix listed.
        """
        intervals = [interval for span in spans for interval in OsvAdapter._advisories_intervals(span)]
        match OsvAdapter._advisories_version(locked):
            case None:
                return next((end for _, end in intervals), None)
            case version:
                return next(
                    (
                        end
                        for start, end in intervals
                        if (low := OsvAdapter._advisories_version(start)) is not None
                        and (high := OsvAdapter._advisories_version(end)) is not None
                        and low <= version < high
                    ),
                    None,
                )

    @staticmethod
    def _advisories_build(package: LockedPackage, detail: dict[str, Any]) -> AdvisoryPackage:
        """The advisory as it concerns one package: its kind, summary and the fix of the locked version's branch."""
        affected = [
            entry
            for entry in detail.get("affected", ())
            if entry.get("package", {}).get("name") == package.name
            and entry.get("package", {}).get("ecosystem") == package.ecosystem
        ]
        informational = {(entry.get("database_specific") or {}).get("informational") for entry in affected}
        fixed = OsvAdapter._advisories_fixed(
            package.version, [span for entry in affected for span in entry.get("ranges", ())]
        )
        return AdvisoryPackage(
            id=detail["id"],
            package=package,
            kind=KindPackage.UNMAINTAINED if "unmaintained" in informational else KindPackage.VULNERABILITY,
            summary=detail.get("summary") or detail.get("details", "")[:160] or detail["id"],
            fixed=fixed,
        )

    ############################################################

    ##### PUBLIC #####

    async def advisories(self, packages: tuple[LockedPackage, ...]) -> tuple[AdvisoryPackage, ...]:
        """Every live advisory against the given package versions; withdrawn ones are dropped."""
        chunks = await asyncio.gather(
            *(self._advisories_chunk(chunk) for chunk in batched(packages, BATCH, strict=False))
        )
        pairs = [pair for chunk in chunks for pair in chunk]
        ids = tuple(dict.fromkeys(advisory_id for _, advisory_id in pairs))
        details = dict(zip(ids, await asyncio.gather(*(self._advisories_detail(i) for i in ids)), strict=True))
        return tuple(
            self._advisories_build(package, details[advisory_id])
            for package, advisory_id in pairs
            if not details[advisory_id].get("withdrawn")
        )
