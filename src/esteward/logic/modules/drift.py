"""M7 · drift: the project declares what the fleet says it is.

Every EDamLabs repository states its identity in `pyproject.toml`, `[tool.edamlabs]`: `kind` (what it ships) and
`family` (what it is). A missing declaration is a deterministic fix; a declaration that contradicts the fleet entry
is a human's call, since either side may be the wrong one.
"""

import tomllib
from datetime import datetime
from typing import Final

from esteward.logic.ports import HostPort
from esteward.models.fleet import Fleet
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

MODULE: Final = "drift"
MANIFEST: Final = "pyproject.toml"
FIELDS: Final = ("kind", "family")


class DriftModule:
    """Identity drift of one fleet entry: `[tool.edamlabs]` against the fleet."""

    __slots__ = ("_host", "_now")

    def __init__(self, host: HostPort, now: datetime) -> None:
        self._host = host
        self._now = now

    ##### PRIVATE #####

    @staticmethod
    def _run_declared(text: str | None) -> dict[str, object]:
        """The `[tool.edamlabs]` table of the manifest; empty when the manifest or the table is missing."""
        return tomllib.loads(text).get("tool", {}).get("edamlabs", {}) if text is not None else {}

    @staticmethod
    def _run_finding(field: str, declared: object, expected: str) -> FindingReport:
        """One identity field: equal is OK, absent is a fix to make, different is a contradiction to settle."""
        match declared:
            case value if value == expected:
                verdict, detail = Verdict.OK, f"{field} = {expected}"
            case None:
                verdict, detail = Verdict.ACT, f'declare `{field} = "{expected}"` in {MANIFEST} [tool.edamlabs]'
            case value:
                verdict, detail = Verdict.ESCALATE, f"{MANIFEST} says {field} = {value!r}, the fleet says {expected!r}"
        return FindingReport(
            key=f"{MODULE}:identity:{field}",
            module=MODULE,
            subject="identity",
            check=field,
            verdict=verdict,
            detail=detail,
        )

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The drift report of a fleet entry: one finding per identity field."""
        declared = self._run_declared(await self._host.file(fleet.repo, MANIFEST))
        expected = {"kind": str(fleet.kind), "family": str(fleet.family)}
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=tuple(self._run_finding(field, declared.get(field), expected[field]) for field in FIELDS),
        )
