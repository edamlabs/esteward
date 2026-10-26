"""M1 · deps: the health of every watched dependency and the advisories against every locked package.

Deterministic: verdicts come from the fleet entry's thresholds and from what hosts, registries and the
advisory database report, never from a judgement.
"""

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from typing import Final

from packaging.version import InvalidVersion, Version

from esteward.logic.lockfile import parse_lockfile
from esteward.logic.ports import AdvisoryPort, HostPort, RegistryPort
from esteward.logic.url import host_url, name_url, slug_url
from esteward.models.fleet import DepsFleet, Fleet, WatchFleet
from esteward.models.package import AdvisoryPackage, KindPackage, LockedPackage
from esteward.models.report import FindingReport, Report
from esteward.models.signal import PackageSignal, RepositorySignal
from esteward.models.verdict import Verdict

MODULE: Final = "deps"
GONE_STATUSES: Final = frozenset({"archived", "quarantined", "deprecated"})
LISTED: Final = 5


@dataclass(frozen=True, slots=True)
class RuleDeps[S]:
    """One check on a signal: when `test` holds, the finding gets `verdict` and the rendered `detail`."""

    check: str
    verdict: Verdict
    test: Callable[[S, DepsFleet, datetime], bool]
    detail: Callable[[S, DepsFleet], str]

    @staticmethod
    def ordered(version: str | None) -> tuple[int, Version | str]:
        """Sort key of a version: comparable releases first, unparsable ones after, by text."""
        try:
            return (0, Version(version or ""))
        except InvalidVersion:
            return (1, version or "")

    @staticmethod
    def older(moment: datetime | None, now: datetime, days: int) -> bool:
        """Whether a known moment lies more than `days` before `now`; an unknown moment is never old."""
        return moment is not None and (now - moment).days > days


REPOSITORY_RULES: Final[tuple[RuleDeps[RepositorySignal], ...]] = (
    RuleDeps(
        "moved",
        Verdict.WATCH,
        lambda s, d, n: s.moved_to is not None,
        lambda s, d: f"{s.slug} moved to {s.moved_to}: update the fleet entry",
    ),
    RuleDeps("archived", Verdict.ESCALATE, lambda s, d, n: s.archived, lambda s, d: f"{s.slug} is archived"),
    RuleDeps(
        "dormant",
        Verdict.WATCH,
        lambda s, d, n: RuleDeps.older(s.pushed_at, n, d.push_age_days),
        lambda s, d: f"no push since {s.pushed_at:%Y-%m-%d} (> {d.push_age_days} days)",
    ),
)
PACKAGE_RULES: Final[tuple[RuleDeps[PackageSignal], ...]] = (
    RuleDeps(
        "status",
        Verdict.ESCALATE,
        lambda s, d, n: s.status in GONE_STATUSES,
        lambda s, d: f"registry status: {s.status}",
    ),
    RuleDeps(
        "stale",
        Verdict.WATCH,
        lambda s, d, n: RuleDeps.older(s.released_at, n, d.release_age_days),
        lambda s, d: f"latest release {s.version} on {s.released_at:%Y-%m-%d} (> {d.release_age_days} days)",
    ),
    RuleDeps("yanked", Verdict.WATCH, lambda s, d, n: s.yanked, lambda s, d: f"latest release {s.version} is yanked"),
)
ADVISORY_VERDICTS: Final[Mapping[tuple[KindPackage, bool], Verdict]] = {
    (KindPackage.UNMAINTAINED, True): Verdict.WATCH,
    (KindPackage.UNMAINTAINED, False): Verdict.WATCH,
    (KindPackage.VULNERABILITY, True): Verdict.ACT,
    (KindPackage.VULNERABILITY, False): Verdict.ESCALATE,
}


class DepsModule:
    """Dependency health of one fleet entry."""

    __slots__ = ("_advisories", "_host", "_limit", "_now", "_registries")

    def __init__(
        self,
        host: HostPort,
        registries: Mapping[str, RegistryPort],
        advisories: AdvisoryPort,
        now: datetime,
        concurrency: int = 8,
    ) -> None:
        self._host = host
        self._registries = registries
        self._advisories = advisories
        self._now = now
        self._limit = asyncio.Semaphore(concurrency)

    ##### PRIVATE #####

    def _run_rules[S](
        self, watch: WatchFleet, signal: S, rules: tuple[RuleDeps[S], ...], deps: DepsFleet
    ) -> tuple[FindingReport, ...]:
        """The findings a signal earns under a rule table."""
        return tuple(
            FindingReport(
                key=f"{MODULE}:{watch.name}:{rule.check}",
                module=MODULE,
                subject=watch.name,
                check=rule.check,
                verdict=rule.verdict,
                detail=rule.detail(signal, deps),
            )
            for rule in rules
            if rule.test(signal, deps, self._now)
        )

    def _run_vanished(self, watch: WatchFleet, where: str, url: str) -> tuple[FindingReport, ...]:
        """A watched repository or package the world no longer answers for."""
        return (
            FindingReport(
                key=f"{MODULE}:{watch.name}:vanished:{where}",
                module=MODULE,
                subject=watch.name,
                check="vanished",
                verdict=Verdict.ESCALATE,
                detail=f"{where} not found: {url}",
                url=url,
            ),
        )

    async def _run_repository(self, watch: WatchFleet, deps: DepsFleet) -> tuple[FindingReport, ...]:
        """Findings on the watched repository, none when the entry names no repository."""
        match watch.repo:
            case None:
                return ()
            case url:
                match await self._host.repository(slug_url(url)):
                    case None:
                        return self._run_vanished(watch, "repository", url)
                    case signal:
                        return self._run_rules(watch, signal, REPOSITORY_RULES, deps)

    async def _run_package(self, watch: WatchFleet, deps: DepsFleet) -> tuple[FindingReport, ...]:
        """Findings on the watched registry package, none when the entry names no registry page."""
        match watch.registry:
            case None:
                return ()
            case url:
                match await self._registries[host_url(url)].package(name_url(url)):
                    case None:
                        return self._run_vanished(watch, "package", url)
                    case signal:
                        return self._run_rules(watch, signal, PACKAGE_RULES, deps) + self._run_license(watch, signal)

    def _run_license(self, watch: WatchFleet, signal: PackageSignal) -> tuple[FindingReport, ...]:
        """A license that is no longer the one the project accepted: a legal change, always a human's call."""
        changed = watch.license is not None and signal.license != watch.license
        return (
            (
                FindingReport(
                    key=f"{MODULE}:{watch.name}:license:{signal.license}",
                    module=MODULE,
                    subject=watch.name,
                    check="license",
                    verdict=Verdict.ESCALATE,
                    detail=f"license is {signal.license}, accepted as {watch.license}",
                ),
            )
            if changed
            else ()
        )

    async def _run_watch(self, watch: WatchFleet, deps: DepsFleet) -> tuple[FindingReport, ...]:
        """Every finding on one watched dependency; a single OK finding when it is healthy."""
        async with self._limit:
            repository, package = await asyncio.gather(
                self._run_repository(watch, deps), self._run_package(watch, deps)
            )
        healthy = FindingReport(
            key=f"{MODULE}:{watch.name}:healthy",
            module=MODULE,
            subject=watch.name,
            check="health",
            verdict=Verdict.OK,
            detail="healthy",
        )
        return (*repository, *package) or (healthy,)

    async def _run_locked(self, fleet: Fleet) -> tuple[LockedPackage, ...]:
        """Every registry package pinned by the configured lockfiles, once each."""
        texts = await asyncio.gather(*(self._host.file(fleet.repo, path) for path in fleet.deps.lockfiles))
        return tuple(
            dict.fromkeys(
                package
                for path, text in zip(fleet.deps.lockfiles, texts, strict=True)
                if text is not None
                for package in parse_lockfile(path, text)
            )
        )

    @staticmethod
    def _run_fix(advisories: tuple[AdvisoryPackage, ...]) -> str | None:
        """The version that clears every advisory of the group: the highest fix, None when one has no fix."""
        fixes = [advisory.fixed for advisory in advisories]
        return None if None in fixes else max(fixes, key=RuleDeps.ordered)

    @staticmethod
    def _run_advisory(advisories: tuple[AdvisoryPackage, ...]) -> FindingReport:
        """The advisories of one package version and kind as one finding: one row per package, never per advisory.

        Fixable vulnerabilities act, any unfixable one escalates the package, unmaintained notices are watched.
        """
        first = advisories[0]
        package = first.package
        fixed = DepsModule._run_fix(advisories)
        ids = ", ".join(advisory.id for advisory in advisories[:LISTED]) + (" …" if len(advisories) > LISTED else "")
        what = f"{first.id}: {first.summary}" if len(advisories) == 1 else f"{len(advisories)} advisories: {ids}"
        return FindingReport(
            key=f"{MODULE}:advisory:{first.kind}:{package.name}@{package.version}",
            module=MODULE,
            subject=f"{package.name} {package.version}",
            check=first.kind,
            verdict=ADVISORY_VERDICTS[first.kind, fixed is not None],
            detail=what + (f"; fixed in {fixed}" if fixed else ""),
            url=f"https://osv.dev/vulnerability/{first.id}",
        )

    @staticmethod
    def _run_grouped(advisories: tuple[AdvisoryPackage, ...]) -> tuple[tuple[AdvisoryPackage, ...], ...]:
        """Advisories grouped by package version and kind, in a stable order."""
        ordered = sorted(advisories, key=lambda a: (a.package.name, a.package.version, a.kind, a.id))
        return tuple(tuple(group) for _, group in groupby(ordered, key=lambda a: (a.package, a.kind)))

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The deps report of a fleet entry: watched dependencies, then advisories on locked packages."""
        async with asyncio.TaskGroup() as group:
            watched = [group.create_task(self._run_watch(watch, fleet.deps)) for watch in fleet.deps.watch]
            locked = group.create_task(self._run_locked(fleet))
        advisories = await self._advisories.advisories(locked.result())
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=(
                *(finding for task in watched for finding in task.result()),
                *(self._run_advisory(group) for group in self._run_grouped(advisories)),
            ),
        )
