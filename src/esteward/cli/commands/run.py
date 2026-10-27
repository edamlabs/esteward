"""`esteward run <project>`: run the project's modules, show the verdicts, optionally publish them."""

import asyncio
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Final, Protocol

import msgspec
import structlog
from rich.console import Console
from rich.table import Table

from esteward.core.lifespan import RuntimeLifespan, lifespan
from esteward.core.settings import settings as st
from esteward.logic.dashboard import DASHBOARD_LABEL, ESCALATION_LABEL, StatusDashboard
from esteward.logic.modules.act import ActModule
from esteward.logic.modules.deps import DepsModule
from esteward.logic.modules.docs import DocsModule
from esteward.logic.modules.drift import DriftModule
from esteward.logic.modules.release import ReleaseModule, ReleaseStage
from esteward.logic.modules.security import SecurityModule
from esteward.logic.modules.upstream import UpstreamModule
from esteward.models.fleet import Fleet, ModuleFleet
from esteward.models.issue import OperationIssue
from esteward.models.report import Report

log = structlog.get_logger()


class RunnerModule(Protocol):
    """Any module: a fleet entry in, a report out."""

    async def run(self, fleet: Fleet) -> Report: ...


MODULES: Final[Mapping[ModuleFleet, Callable[[RuntimeLifespan, datetime], RunnerModule]]] = MappingProxyType(
    {
        ModuleFleet.DEPS: lambda rt, now: DepsModule(rt.github, rt.registries, rt.advisories, now, st.concurrency),
        ModuleFleet.SECURITY: lambda rt, now: SecurityModule(rt.github, now, st.concurrency),
        ModuleFleet.DRIFT: lambda rt, now: DriftModule(rt.github, now),
        ModuleFleet.RELEASE: lambda rt, now: ReleaseModule(rt.github, rt.github, now),
        ModuleFleet.UPSTREAM: lambda rt, now: UpstreamModule(rt.github, rt.registries, now),
        ModuleFleet.DOCS: lambda rt, now: DocsModule(rt.github, rt.site, rt.workspace, now, concurrency=st.concurrency),
    }
)


def _run_table(reports: tuple[Report, ...]) -> Table:
    """The verdicts as a terminal table, most severe first."""
    table = Table("module", "verdict", "subject", "check", "detail", title=reports[0].repo if reports else None)
    rows = sorted(((r.module, f) for r in reports for f in r.findings), key=lambda row: (-row[1].verdict.rank, row[0]))
    deque((table.add_row(module, str(f.verdict), f.subject, f.check, f.detail) for module, f in rows), maxlen=0)
    return table


async def _run_stages(
    rt: RuntimeLifespan,
    fleet: Fleet,
    reports: tuple[Report, ...],
    *,
    act: bool,
    release: bool,
    publish: bool,
    now: datetime,
) -> tuple[Report, ...]:
    """The stages that carry out the reports' act findings: act over deps, release over release."""
    acted = [
        (await ActModule(rt.workspace, rt.advisories, rt.github, publish=publish).run(fleet, report))
        if act and report.module == ModuleFleet.DEPS
        else report
        for report in reports
    ]
    released = [
        (await ReleaseStage(rt.workspace, rt.github, rt.github, now, publish=publish).run(fleet, report))
        if release and report.module == ModuleFleet.RELEASE
        else report
        for report in acted
    ]
    return tuple(released)


async def _run_modules(
    fleet: Fleet, modules: tuple[ModuleFleet, ...], *, publish: bool, act: bool, release: bool
) -> tuple[tuple[Report, ...], tuple[OperationIssue, ...]]:
    """Every selected module concurrently, the stages over their reports, then the tracker operations."""
    now = datetime.now(UTC)
    async with lifespan(st) as rt:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(MODULES[module](rt, now).run(fleet)) for module in modules]
        reports = await _run_stages(
            rt, fleet, tuple(task.result() for task in tasks), act=act, release=release, publish=publish, now=now
        )
        dashboard, escalations = await asyncio.gather(
            rt.github.issues(fleet.repo, DASHBOARD_LABEL), rt.github.issues(fleet.repo, ESCALATION_LABEL)
        )
        operations = StatusDashboard().plan(reports, dashboard, escalations)
        await asyncio.gather(*(rt.github.apply(fleet.repo, operation) for operation in (operations if publish else ())))
    return reports, operations


def _run_write(report_dir: Path | None, reports: tuple[Report, ...]) -> None:
    """One `<module>.json` per report in `report_dir`, when one is given."""
    match report_dir:
        case None:
            return
        case directory:
            directory.mkdir(parents=True, exist_ok=True)
            deque(((directory / f"{r.module}.json").write_bytes(msgspec.json.encode(r)) for r in reports), maxlen=0)


def run(
    project: str,
    *,
    module: tuple[ModuleFleet, ...] = (),
    act: bool = False,
    release: bool = False,
    publish: bool = False,
    report_dir: Path | None = None,
) -> None:
    """Run the enabled modules of `fleet/<project>.toml`.

    Args:
        project: Fleet entry name (the TOML file stem).
        module: Restrict the run to these modules; default: every module the entry enables.
        act: Carry out the deps module's fixable findings: one self-merging PR per lockfile-only bump.
        release: Carry out the release module's decisions: the folded version's tag, the due release's PR.
        publish: Apply the dashboard and escalation operations to the project's tracker.
        report_dir: Write one `<module>.json` report per module there.
    """
    fleet = Fleet.load(st.fleet_dir / f"{project}.toml")
    selected = tuple(m for m in fleet.modules if not module or m in module)
    reports, operations = asyncio.run(_run_modules(fleet, selected, publish=publish, act=act, release=release))
    _run_write(report_dir, reports)
    Console().print(_run_table(reports))
    log.info(
        "run_done",
        repo=fleet.repo,
        modules=[str(m) for m in selected],
        act=act,
        release=release,
        operations=len(operations),
        published=publish,
    )
