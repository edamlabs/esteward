"""M7 · drift: the project declares what the fleet says it is.

Every EDamLabs repository states its identity in its manifest: `pyproject.toml` `[tool.edamlabs]`, or for a Rust
project `Cargo.toml` `[package.metadata.edamlabs]` (`[workspace.metadata.edamlabs]` in a workspace): `kind` (what it
ships) and `family` (what it is). A missing declaration is a deterministic fix; a declaration that contradicts the fleet entry
is a human's call, since either side may be the wrong one.
"""

import asyncio
import tomllib
from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from esteward.logic.ports import HostPort
from esteward.models.fleet import Fleet
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

MODULE: Final = "drift"
FIELDS: Final = ("kind", "family")
### Manifest → where its EDamLabs table lives; the first manifest declaring one wins, in this order.
MANIFESTS: Final[Mapping[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]]] = MappingProxyType(
    {
        "pyproject.toml": ("pyproject.toml [tool.edamlabs]", lambda doc: doc.get("tool", {}).get("edamlabs", {})),
        "Cargo.toml": (
            "Cargo.toml [package.metadata.edamlabs]",
            lambda doc: (
                doc.get("package", {}).get("metadata", {}).get("edamlabs")
                or doc.get("workspace", {}).get("metadata", {}).get("edamlabs")
                or {}
            ),
        ),
    }
)


class DriftModule:
    """Identity drift of one fleet entry: `[tool.edamlabs]` against the fleet."""

    __slots__ = ("_host", "_now")

    def __init__(self, host: HostPort, now: datetime) -> None:
        self._host = host
        self._now = now

    ##### PRIVATE #####

    async def _run_declared(self, repo: str) -> tuple[str, dict[str, Any]]:
        """Where the identity is (or should be) declared, and the declared table; empty when none declares it."""
        texts = await asyncio.gather(*(self._host.file(repo, name) for name in MANIFESTS))
        found = [
            (MANIFESTS[name][0], MANIFESTS[name][1](tomllib.loads(text)))
            for name, text in zip(MANIFESTS, texts, strict=True)
            if text is not None
        ]
        default = (found[0][0], {}) if found else (MANIFESTS["pyproject.toml"][0], {})
        return next((entry for entry in found if entry[1]), default)

    @staticmethod
    def _run_finding(field: str, declared: object, expected: str, where: str) -> FindingReport:
        """One identity field: equal is OK, absent is a fix to make, different is a contradiction to settle."""
        match declared:
            case value if value == expected:
                verdict, detail = Verdict.OK, f"{field} = {expected}"
            case None:
                verdict, detail = Verdict.ACT, f'declare `{field} = "{expected}"` in {where}'
            case value:
                verdict, detail = Verdict.ESCALATE, f"{where} says {field} = {value!r}, the fleet says {expected!r}"
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
        where, declared = await self._run_declared(fleet.repo)
        expected = {"kind": str(fleet.kind), "family": str(fleet.family)}
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=tuple(self._run_finding(field, declared.get(field), expected[field], where) for field in FIELDS),
        )
