"""M2 · upstream: the engines a binding mirrors, against their newest release.

Detection only. The repository's own sync flow owns the mirror and the public API diff (its `apidiff`
tooling); the module says when an engine has moved past the declared parity, and who must act: the
agent where one exists, a human where none does.
"""

import asyncio
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from packaging.version import InvalidVersion, Version

from esteward.logic.ports import HostPort, RegistryPort
from esteward.models.fleet import EngineFleet, Fleet
from esteward.models.report import FindingReport, Report
from esteward.models.signal import PackageSignal
from esteward.models.verdict import Verdict
from esteward.ops.url import Url

MODULE: Final = "upstream"
### Either workflow means the repository has an agent that owns the mirror update.
AGENTS: Final = (".github/workflows/sync.yml", ".github/workflows/maintenance.yml")


class UpstreamModule:
    """Upstream parity of one fleet entry: every declared engine against its newest release."""

    __slots__ = ("_host", "_now", "_registries")

    def __init__(self, host: HostPort, registries: Mapping[str, RegistryPort], now: datetime) -> None:
        self._host = host
        self._registries = registries
        self._now = now

    ##### PRIVATE #####

    @staticmethod
    def _run_finding(engine: EngineFleet, verdict: Verdict, detail: str) -> FindingReport:
        """One parity row of one engine."""
        return FindingReport(
            key=f"{MODULE}:{engine.name}:parity",
            module=MODULE,
            subject=engine.name,
            check="parity",
            verdict=verdict,
            detail=detail,
        )

    @staticmethod
    def _run_version(text: str) -> Version | None:
        """One version text parsed; None when the registry or the fleet entry speaks nonsense."""
        try:
            return Version(text)
        except InvalidVersion:
            return None

    @staticmethod
    def _run_parity(engine: EngineFleet, signal: PackageSignal, *, agent: bool) -> FindingReport:
        """The newest release against the declared parity: who owns the gap, if any."""
        match UpstreamModule._run_version(signal.newest), UpstreamModule._run_version(engine.parity):
            case Version() as newest, Version() as parity if newest > parity:
                label = (
                    "the repository's sync flow owns the mirror"
                    if agent
                    else ("the repository has no sync flow: a human sets the new parity")
                )
                verdict = Verdict.WATCH if agent else Verdict.ESCALATE
                return UpstreamModule._run_finding(
                    engine, verdict, f"the engine released {signal.newest} beyond parity {engine.parity}: {label}"
                )
            case Version() as newest, Version() as parity if newest < parity:
                return UpstreamModule._run_finding(
                    engine,
                    Verdict.ESCALATE,
                    f"parity {engine.parity} is ahead of the engine's newest {signal.newest}: the declaration is wrong",
                )
            case Version(), Version():
                return UpstreamModule._run_finding(
                    engine, Verdict.OK, f"parity {engine.parity} is the engine's newest release"
                )
            case _:
                return UpstreamModule._run_finding(
                    engine,
                    Verdict.WATCH,
                    f"cannot order the engine's newest {signal.newest} against parity {engine.parity}",
                )

    async def _run_engine(self, engine: EngineFleet, *, agent: bool) -> FindingReport:
        """One engine: its registry page, then the parity row."""
        page = Url(engine.registry)
        match await self._registries[page.host()].package(page.name()):
            case None:
                return UpstreamModule._run_finding(
                    engine, Verdict.ESCALATE, f"{engine.registry} not found: the engine's registry page is gone"
                )
            case signal:
                return UpstreamModule._run_parity(engine, signal, agent=agent)

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The upstream report of a fleet entry: one parity row per declared engine."""
        tree = await self._host.tree(fleet.repo)
        agent = any(workflow in tree for workflow in AGENTS)
        findings = await asyncio.gather(*(self._run_engine(engine, agent=agent) for engine in fleet.upstream.engines))
        return Report(repo=fleet.repo, module=MODULE, generated=self._now, findings=tuple(findings))
