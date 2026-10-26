"""L1 · act: lockfile-only vulnerability bumps, executed; one self-merging pull request per finding key.

Deterministic: the ecosystem's solver runs in a fresh checkout, and the bumped lockfile is the evidence.
A solver that cannot reach the fix is answered by the reverse dependency tree — an intermediate package
blocks upstream (watch, with the chain as evidence); the project's own manifest calls for a human
(escalate). Bumps that need a manifest range change are out of this slice.
"""

import asyncio
import re
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import groupby
from typing import Final

from msgspec.structs import replace as restruct

from esteward.logic.advisories import GroupAdvisories
from esteward.logic.bump import BUMPERS, ChainBump
from esteward.logic.lockfile import parse_lockfile
from esteward.logic.modules import deps
from esteward.logic.ports import AdvisoryPort, TrackerPort, WorkspacePort
from esteward.models.fleet import Fleet
from esteward.models.package import AdvisoryPackage, KindPackage, LockedPackage
from esteward.models.pull import AutomergePull, CreatePull, Pull, UpdatePull
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

### Branch names live in refs and URLs: only this set survives, everything else becomes one dash —
### dots go too, so git's `..`, trailing-dot and `.lock` ref rules can never be hit.
BRANCH_NAME: Final = re.compile(r"[^A-Za-z0-9_-]+")
EXCERPT: Final = 200


@dataclass(frozen=True, slots=True)
class TaskAct:
    """One lockfile's share of one finding key: the bump to run, and the advisories it clears."""

    lockfile: str
    package: LockedPackage
    fix: str
    advisories: tuple[AdvisoryPackage, ...]


class ActModule:
    """Lockfile-only vulnerability bumps of one fleet entry, executed in its checkout."""

    __slots__ = ("_advisories", "_publish", "_tracker", "_workspace")

    def __init__(
        self, workspace: WorkspacePort, advisories: AdvisoryPort, tracker: TrackerPort, *, publish: bool = False
    ) -> None:
        self._workspace = workspace
        self._advisories = advisories
        self._tracker = tracker
        self._publish = publish

    ##### PRIVATE #####

    @staticmethod
    def _task_key(package: LockedPackage) -> str:
        """The finding key the deps module gave this package's vulnerabilities."""
        return f"{deps.MODULE}:advisory:{KindPackage.VULNERABILITY}:{package.name}@{package.version}"

    @staticmethod
    def _tasks_group(
        group: tuple[AdvisoryPackage, ...], fix: str | None, spots: Mapping[LockedPackage, tuple[str, ...]]
    ) -> tuple[tuple[str, TaskAct], ...]:
        """The per-lockfile tasks of one advisory group; empty when the group has no fix."""
        match fix:
            case None:
                return ()
            case version:
                package = group[0].package
                key = ActModule._task_key(package)
                return tuple((key, TaskAct(lockfile, package, version, group)) for lockfile in spots[package])

    async def _run_tasks(self, fleet: Fleet) -> Mapping[str, tuple[TaskAct, ...]]:
        """Every fixable vulnerability of the checkout, by finding key, in key order."""
        await self._workspace.checkout(fleet.repo)
        texts = await asyncio.gather(*(self._workspace.read(path) for path in fleet.deps.lockfiles))
        pinned = sorted(
            (
                (path, package)
                for path, text in zip(fleet.deps.lockfiles, texts, strict=True)
                if text is not None
                for package in parse_lockfile(path, text)
            ),
            key=lambda spot: (spot[1].ecosystem, spot[1].name, spot[1].version),
        )
        spots = {
            package: tuple(path for path, _ in group) for package, group in groupby(pinned, key=lambda spot: spot[1])
        }
        advisories = await self._advisories.advisories(tuple(spots))
        grouped = GroupAdvisories(advisories)
        tasks = sorted(
            (
                task
                for group in grouped.groups()
                if group[0].kind is KindPackage.VULNERABILITY
                for task in ActModule._tasks_group(group, grouped.fix(group), spots)
            ),
            key=lambda entry: entry[0],
        )
        return {key: tuple(task for _, task in group) for key, group in groupby(tasks, key=lambda entry: entry[0])}

    async def _run_solve(self, task: TaskAct) -> str | None:
        """Solve one lockfile's bump; None on success, the reason as text on failure."""
        bumper = BUMPERS[task.package.ecosystem]
        outcome = await self._workspace.run(bumper.solver(task.lockfile, task.package, task.fix))
        match outcome.rc:
            case 0:
                return await self._run_verify(task)
            case _:
                return outcome.err.strip() or outcome.out.strip() or f"the solver failed with rc {outcome.rc}"

    async def _run_verify(self, task: TaskAct) -> str | None:
        """The bumped lockfile as evidence: the fix pinned, the vulnerable version gone."""
        match await self._workspace.read(task.lockfile):
            case None:
                return f"{task.lockfile} vanished after the solver ran"
            case text:
                packages = parse_lockfile(task.lockfile, text)
                stuck = task.package in packages
                reached = LockedPackage(task.package.ecosystem, task.package.name, task.fix) in packages
                return (
                    None
                    if reached and not stuck
                    else f"the solver reported success but {task.lockfile} still pins {task.package.name} {task.package.version}"
                )

    async def _run_stuck(self, task: TaskAct, reason: str, finding: FindingReport) -> FindingReport:
        """A fix the solver cannot reach: the reverse tree says whether upstream blocks or the manifest does."""
        bumper = BUMPERS[task.package.ecosystem]
        outcome = await self._workspace.run(bumper.tree(task.lockfile, task.package))
        chain = ChainBump(outcome.out if outcome.rc == 0 else "")
        match chain.walk():
            case ():
                excerpt = next(iter(reason.splitlines()), reason)[:EXCERPT]
                return restruct(
                    finding,
                    verdict=Verdict.ESCALATE,
                    detail=f"{finding.detail}; the solver cannot reach {task.fix}: {excerpt}",
                )
            case _:
                manifest = chain.direct()
                label = "the fix needs a manifest change" if manifest else "blocked upstream"
                return restruct(
                    finding,
                    verdict=Verdict.ESCALATE if manifest else Verdict.WATCH,
                    detail=f"{finding.detail}; {label}: {chain.render()}",
                )

    @staticmethod
    def _run_branch(key: str) -> str:
        """One branch per finding key: a re-run updates its pull request instead of duplicating it."""
        return f"esteward/act/{BRANCH_NAME.sub('-', key).strip('-')}"

    @staticmethod
    def _run_title(tasks: tuple[TaskAct, ...]) -> str:
        first = tasks[0]
        return f"fix(deps): {first.package.name} {first.package.version} → {first.fix}"

    @staticmethod
    def _run_body(key: str, tasks: tuple[TaskAct, ...]) -> str:
        """The pull request body: the evidence, the bumps, and the marker tying it to its finding key."""
        first = tasks[0]
        count = len(first.advisories)
        ids = ", ".join(advisory.id for advisory in first.advisories[: deps.LISTED])
        listed = f"{ids} …" if count > deps.LISTED else ids
        bumps = "".join(f"- `{task.lockfile}` → `{task.fix}`\n" for task in tasks)
        return (
            f"<!-- esteward:key={key} -->\n"
            f"`{first.package.name} {first.package.version}` carries {count} "
            f"{'advisory' if count == 1 else 'advisories'}: {listed}.\n\n"
            f"Lockfile-only {'bump' if len(tasks) == 1 else 'bumps'}:\n{bumps}\n"
            f"_Opened by esteward; it merges itself when every required check passes._\n"
        )

    async def _run_pull(self, slug: str, key: str, tasks: tuple[TaskAct, ...]) -> Pull:
        """Commit, push, and the one idempotent self-merging pull request of one finding key."""
        branch = ActModule._run_branch(key)
        title, body = ActModule._run_title(tasks), ActModule._run_body(key, tasks)
        match await self._workspace.commit(branch, title):
            case True:
                await self._workspace.push(branch)
            case _:
                message = f"the solver verified {key} but the checkout shows no change"
                raise RuntimeError(message)
        match await self._tracker.pull(slug, branch):
            case None:
                await self._tracker.apply(slug, CreatePull(branch, title, body))
                match await self._tracker.pull(slug, branch):
                    case None:
                        message = f"pull request {branch} vanished right after creation"
                        raise RuntimeError(message)
                    case created:
                        return created
            case existing:
                pending = (
                    *((UpdatePull(existing.number, body),) if existing.body != body else ()),
                    *((AutomergePull(existing.node),) if not existing.automerge else ()),
                )
                await asyncio.gather(*(self._tracker.apply(slug, operation) for operation in pending))
                return existing

    async def _run_key(self, slug: str, key: str, tasks: tuple[TaskAct, ...], finding: FindingReport) -> FindingReport:
        """One finding key: solve each lockfile; a failure explains itself, a success opens its pull request."""
        try:
            solved = [(task, await self._run_solve(task)) for task in tasks]
            done = tuple(task for task, reason in solved if reason is None)
            failed = next(((task, reason) for task, reason in solved if reason is not None), None)
            match failed:
                case (task, reason):
                    finding = await self._run_stuck(task, reason, finding)
                case _:
                    pass
            match done:
                case ():
                    return finding
                case _:
                    match self._publish:
                        case True:
                            pull = await self._run_pull(slug, key, done)
                            return restruct(finding, detail=f"{finding.detail} · [PR #{pull.number}]({pull.url})")
                        case False if failed is None:
                            return restruct(finding, detail=f"{finding.detail} · bump verified (dry run)")
                        case _:
                            return finding
        finally:
            await self._workspace.restore()

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet, report: Report) -> Report:
        """The deps report with every fixable vulnerability finding carried out or explained."""
        wanted = {
            finding.key: finding
            for finding in report.findings
            if finding.verdict is Verdict.ACT
            and finding.module == deps.MODULE
            and finding.check == KindPackage.VULNERABILITY
        }
        tasks = await self._run_tasks(fleet) if wanted else {}
        acted = {
            key: await self._run_key(fleet.repo, key, group, wanted[key])
            for key, group in tasks.items()
            if key in wanted
        }
        return restruct(report, findings=tuple(acted.get(finding.key, finding) for finding in report.findings))
