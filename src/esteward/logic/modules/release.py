"""M3 · release: the deterministic release decision of one fleet entry, and the stage that carries it out.

The policy is the TODO's, decided by records alone: a release is cut when `## [Unreleased]` carries content
and the oldest unreleased commit is older than the fleet's age — at once when a Fixed or Security entry is
waiting. Patch by default, minor on an `### Added` section or a `feat:` commit, and never major: a breaking
change escalates. The stage folds the changelog exactly like e-serde's proven release workflow, bumps the
static version fields, re-syncs the root lockfiles, and opens one self-merging PR per version; the tag of a
merged release PR is pushed on a later run, and the repository's own tag-driven workflow publishes it.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from msgspec.structs import replace as restruct
from packaging.version import Version

from esteward.logic.ports import HostPort, TrackerPort, WorkspacePort
from esteward.models.fleet import Fleet, ReleaseFleet
from esteward.models.pull import AutomergePull, CreatePull, Pull, UpdatePull
from esteward.models.report import FindingReport, Report
from esteward.models.signal import CommitSignal
from esteward.models.verdict import Verdict
from esteward.ops.changelog import Changelog
from esteward.ops.semver import PREFIX, LevelSemver, Semver

MODULE: Final = "release"
CHANGELOG: Final = "CHANGELOG.md"
MANIFESTS: Final = ("pyproject.toml", "Cargo.toml")
### One sync per root lockfile: the argv, the lockfile it rewrites, the manifest whose bump demands it.
SYNC_LOCKS: Final = (
    (("cargo", "update", "--workspace"), "Cargo.lock", "Cargo.toml"),
    (("uv", "lock"), "uv.lock", "pyproject.toml"),
)
SKIPPED: Final = ("chore(release)", "Merge ")
### Conventional commits: `feat!:` or `fix(scope)!:` announces a breaking change.
BREAKING: Final = re.compile(r"^\w+(?:\([^)]*\))?!:")
BREAKING_SECTION: Final = "breaking"
FEATURES: Final = ("feat:", "feat(")
IMMEDIATE: Final = frozenset({"Fixed", "Security"})
MINOR: Final = frozenset({"Added"})
EXCERPT: Final = 200


class KeyRelease(StrEnum):
    """The finding keys of the release module: one pending decision, one tag reconciliation."""

    PENDING = "release:pending"
    TAG = "release:tag"


@dataclass(frozen=True, slots=True)
class PlanRelease:
    """One repository's release decision: what is folded, what is tagged, what to cut next, and why."""

    verdict: Verdict
    reason: str
    next: str | None
    level: LevelSemver | None
    folded: str | None
    tag: str | None
    subjects: tuple[str, ...] = ()

    ##### PRIVATE #####

    @staticmethod
    def _decide_subjects(commits: tuple[CommitSignal, ...]) -> tuple[str, ...]:
        """The unreleased subjects, without the release commits and the merge noise: the fold's fallback."""
        return tuple(commit.subject for commit in commits if not commit.subject.startswith(SKIPPED))

    @classmethod
    def _decide_pending(
        cls,
        changelog: Changelog,
        folded: str,
        version: str,
        *,
        commits: tuple[CommitSignal, ...],
        settings: ReleaseFleet,
        now: datetime,
        subjects: tuple[str, ...],
    ) -> PlanRelease:
        """The pending decision: the unreleased section's content, its breaking markers, and its age."""
        sections = changelog.sections()
        immediate = bool(IMMEDIATE & sections)
        breaking = any(BREAKING.match(subject) for subject in subjects) or any(
            BREAKING_SECTION in section.lower() for section in sections
        )
        level = (
            LevelSemver.MINOR
            if MINOR & sections or any(subject.startswith(FEATURES) for subject in subjects)
            else LevelSemver.PATCH
        )
        age = (now - commits[0].committed).days if commits else None
        due = immediate or (age is not None and age > settings.unreleased_age_days)
        match changelog.unreleased(), breaking, age, due:
            case (), _, _, _:
                return cls(Verdict.OK, "no unreleased content", None, None, folded, version, subjects)
            case _, True, _, _:
                return cls(
                    Verdict.ESCALATE,
                    "breaking change unreleased: a major version is a human decision",
                    None,
                    None,
                    folded,
                    version,
                    subjects,
                )
            case _, _, None, _:
                return cls(
                    Verdict.ESCALATE,
                    f"unreleased content but no commit since v{version}: it cannot be dated",
                    None,
                    None,
                    folded,
                    version,
                    subjects,
                )
            case _, _, _, True:
                reason = (
                    "a Fixed or Security entry releases at once"
                    if immediate
                    else f"the oldest unreleased commit is {age} days old (> {settings.unreleased_age_days})"
                )
                next_version = Semver(version).bump(level)
                return cls(
                    Verdict.ACT,
                    f"release v{next_version} ({level}): {reason}",
                    next_version,
                    level,
                    folded,
                    version,
                    subjects,
                )
            case _:
                return cls(
                    Verdict.OK,
                    f"unreleased content waits: the oldest commit is {age} days old (<= {settings.unreleased_age_days})",
                    None,
                    None,
                    folded,
                    version,
                    subjects,
                )

    @classmethod
    def _decide_folded(
        cls,
        changelog: Changelog,
        version: str,
        *,
        commits: tuple[CommitSignal, ...],
        settings: ReleaseFleet,
        now: datetime,
        subjects: tuple[str, ...],
    ) -> PlanRelease:
        """The decision once changelog and newest tag are known: a fold awaiting its tag goes first."""
        match changelog.latest():
            case None:
                return cls(
                    Verdict.ESCALATE, "the changelog names no released version", None, None, None, version, subjects
                )
            case folded:
                match Version(folded) > Version(version):
                    case True:
                        return cls(
                            Verdict.WATCH,
                            f"v{folded} is folded but untagged: that release goes first",
                            None,
                            None,
                            folded,
                            version,
                            subjects,
                        )
                    case _:
                        return cls._decide_pending(
                            changelog, folded, version, commits=commits, settings=settings, now=now, subjects=subjects
                        )

    ############################################################

    ##### PUBLIC #####

    @staticmethod
    def branch(version: str) -> str:
        """The engine's release branch of one version: one branch per version keeps the PR idempotent."""
        return f"esteward/release/v{version}"

    @classmethod
    def decide(
        cls,
        changelog: Changelog | None,
        tags: tuple[str, ...],
        commits: tuple[CommitSignal, ...],
        settings: ReleaseFleet,
        now: datetime,
    ) -> PlanRelease:
        """The release decision one repository's changelog, tags and unreleased commits earn."""
        tag = Semver.latest(tags)
        subjects = PlanRelease._decide_subjects(commits)
        match changelog:
            case None:
                return cls(
                    Verdict.ESCALATE,
                    "no CHANGELOG.md: the fleet baseline requires one",
                    None,
                    None,
                    None,
                    tag.removeprefix(PREFIX) if tag else None,
                    subjects,
                )
            case _:
                match tag:
                    case None:
                        return cls(
                            Verdict.ESCALATE,
                            "no v* tag: the first release is a human decision",
                            None,
                            None,
                            changelog.latest(),
                            None,
                            subjects,
                        )
                    case _:
                        return cls._decide_folded(
                            changelog,
                            tag.removeprefix(PREFIX),
                            commits=commits,
                            settings=settings,
                            now=now,
                            subjects=subjects,
                        )


class ReleaseModule:
    """The release report of one fleet entry: the pending decision and the tag reconciliation."""

    __slots__ = ("_host", "_now", "_tracker")

    def __init__(self, host: HostPort, tracker: TrackerPort, now: datetime) -> None:
        self._host = host
        self._tracker = tracker
        self._now = now

    ##### PRIVATE #####

    @staticmethod
    def _run_finding(key: KeyRelease, verdict: Verdict, detail: str) -> FindingReport:
        """One release finding: the key names the row, the detail carries the evidence."""
        return FindingReport(
            key=key,
            module=MODULE,
            subject="release",
            check=key.removeprefix(f"{MODULE}:"),
            verdict=verdict,
            detail=detail,
        )

    async def _run_plan(self, repo: str, settings: ReleaseFleet) -> PlanRelease:
        """The release plan of one repository, from its changelog, tags and unreleased commits."""
        text = await self._host.file(repo, CHANGELOG)
        tags = await self._host.tags(repo)
        latest = Semver.latest(tags)
        commits = await self._host.commits(repo, latest) if latest else ()
        return PlanRelease.decide(Changelog(text) if text is not None else None, tags, commits, settings, self._now)

    async def _run_tagged(self, repo: str, plan: PlanRelease) -> FindingReport:
        """The tag row: whether the changelog's newest folded version carries its tag."""
        match plan.folded, plan.tag:
            case str() as folded, str() as tag if Version(folded) > Version(tag):
                branch = PlanRelease.branch(folded)
                match await self._tracker.merged(repo, branch):
                    case Pull(number=number):
                        return self._run_finding(
                            KeyRelease.TAG,
                            Verdict.ACT,
                            f"tag v{folded} pending: release PR #{number} merged, the tag is not pushed",
                        )
                    case _:
                        match await self._tracker.pull(repo, branch):
                            case Pull(number=number):
                                return self._run_finding(KeyRelease.TAG, Verdict.WATCH, f"release PR #{number} is open")
                            case _:
                                return self._run_finding(
                                    KeyRelease.TAG,
                                    Verdict.ESCALATE,
                                    f"v{folded} is folded without an engine release PR: tag it by hand",
                                )
            case _:
                detail = (
                    "nothing folded and tagged to reconcile yet"
                    if plan.folded is None or plan.tag is None
                    else f"v{plan.tag}: the tag and the changelog agree"
                )
                return self._run_finding(KeyRelease.TAG, Verdict.OK, detail)

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The release report of a fleet entry: the pending decision and the tag reconciliation."""
        plan = await self._run_plan(fleet.repo, fleet.release)
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=(
                self._run_finding(KeyRelease.PENDING, plan.verdict, plan.reason),
                await self._run_tagged(fleet.repo, plan),
            ),
        )


class ReleaseStage:
    """The release decisions carried out: the pending tag pushed, the due release opened as a self-merging PR."""

    __slots__ = ("_host", "_now", "_publish", "_tracker", "_workspace")

    def __init__(
        self,
        workspace: WorkspacePort,
        host: HostPort,
        tracker: TrackerPort,
        now: datetime,
        *,
        publish: bool = False,
    ) -> None:
        self._workspace = workspace
        self._host = host
        self._tracker = tracker
        self._now = now
        self._publish = publish

    ##### PRIVATE #####

    @staticmethod
    def _release_manifest(text: str, current: str, version: str) -> str | None:
        """The manifest with its static version moved; None when it declares no `version = "<current>"`."""
        declared = f'version = "{current}"'
        return text.replace(declared, f'version = "{version}"', 1) if declared in text else None

    @staticmethod
    def _release_body(plan: PlanRelease, changelog: Changelog) -> str:
        """The release PR's body: the bump, the curated notes the fold carries, and the engine's marker."""
        notes = changelog.unreleased()
        return (
            f"<!-- esteward:release:v{plan.next} -->\n"
            f"{plan.level} release: v{plan.tag} → v{plan.next}.\n\n"
            f"{'\n'.join(notes)}\n\n"
            f"_Opened by esteward; it merges itself when every required check passes._\n"
        )

    async def _run_changelog(self, repo: str) -> str:
        """The changelog of the checkout; a release repository without one is an infrastructure fault."""
        match await self._workspace.read(CHANGELOG):
            case None:
                message = f"{repo}: the checkout has no {CHANGELOG}"
                raise RuntimeError(message)
            case text:
                return text

    async def _run_plan(self, repo: str, changelog: Changelog, settings: ReleaseFleet) -> PlanRelease:
        """The plan re-decided over the checkout's own changelog: the disk is the truth the fold touches."""
        tags = await self._host.tags(repo)
        latest = Semver.latest(tags)
        commits = await self._host.commits(repo, latest) if latest else ()
        return PlanRelease.decide(changelog, tags, commits, settings, self._now)

    async def _run_tag(self, fleet: Fleet, finding: FindingReport) -> FindingReport:
        """Push the tag of the folded version: the repository's own release flow publishes it."""
        await self._workspace.checkout(fleet.repo)
        folded = Changelog(await self._run_changelog(fleet.repo)).latest()
        match folded:
            case None:
                message = f"{fleet.repo}: the changelog names no version to tag"
                raise RuntimeError(message)
            case version:
                match await self._tracker.merged(fleet.repo, PlanRelease.branch(version)):
                    case Pull(merge_sha=str() as sha):
                        match self._publish:
                            case True:
                                await self._workspace.tag(f"v{version}", sha)
                                return restruct(finding, detail=f"{finding.detail} · tagged v{version}")
                            case _:
                                return restruct(finding, detail=f"{finding.detail} · tag v{version} ready (dry run)")
                    case _:
                        message = f"the release PR of v{version} is no longer merged: nothing to tag"
                        raise RuntimeError(message)

    async def _run_manifests(self, current: str, version: str) -> frozenset[str]:
        """Bump every static version field; a dynamic manifest declares none and is skipped."""
        texts = await asyncio.gather(*(self._workspace.read(name) for name in MANIFESTS))
        bumped = {
            name: moved
            for name, text in zip(MANIFESTS, texts, strict=True)
            if text is not None and (moved := ReleaseStage._release_manifest(text, current, version)) is not None
        }
        await asyncio.gather(*(self._workspace.write(name, text) for name, text in bumped.items()))
        return frozenset(bumped)

    async def _run_locks(self, changed: frozenset[str]) -> None:
        """Re-sync every root lockfile whose manifest moved; a sync that fails is an infrastructure fault."""
        syncs = [
            argv
            for argv, lock, manifest in SYNC_LOCKS
            if manifest in changed and await self._workspace.read(lock) is not None
        ]
        outcomes = [(argv, await self._workspace.run(argv)) for argv in syncs]
        match next(((argv, outcome) for argv, outcome in outcomes if outcome.rc), None):
            case None:
                return
            case failure:
                argv, outcome = failure
                message = f"{' '.join(argv)} failed: {(outcome.err.strip() or outcome.out.strip())[:EXCERPT]}"
                raise RuntimeError(message)

    async def _run_pull(self, slug: str, branch: str, title: str, body: str) -> Pull:
        """Commit, push, and the one idempotent self-merging release PR of one version."""
        match await self._workspace.commit(branch, title):
            case True:
                await self._workspace.push(branch)
            case _:
                message = f"the release fold of {slug} changed nothing: nothing to open"
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

    async def _run_release(self, fleet: Fleet, finding: FindingReport) -> FindingReport:
        """Fold the changelog, bump the manifests, sync the locks, and open the self-merging release PR."""
        await self._workspace.checkout(fleet.repo)
        changelog = Changelog(await self._run_changelog(fleet.repo))
        plan = await self._run_plan(fleet.repo, changelog, fleet.release)
        match plan.next, plan.level, plan.tag:
            case str() as version, LevelSemver(), str() as current:
                await self._workspace.write(CHANGELOG, changelog.fold(version, f"{self._now:%Y-%m-%d}", plan.subjects))
                await self._run_locks(await self._run_manifests(current, version))
                match self._publish:
                    case False:
                        return restruct(finding, detail=f"{finding.detail} · release prepared (dry run)")
                    case _:
                        pull = await self._run_pull(
                            fleet.repo,
                            PlanRelease.branch(version),
                            f"chore(release): v{version}",
                            ReleaseStage._release_body(plan, changelog),
                        )
                        return restruct(finding, detail=f"{finding.detail} · [PR #{pull.number}]({pull.url})")
            case _:
                ### The world moved between the report and the stage: the next run decides again.
                return finding

    async def _run_carry(self, fleet: Fleet, key: str, finding: FindingReport) -> FindingReport:
        """Carry out one act finding of the release report."""
        match key:
            case KeyRelease.TAG:
                return await self._run_tag(fleet, finding)
            case KeyRelease.PENDING:
                return await self._run_release(fleet, finding)
            case _:
                return finding

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet, report: Report) -> Report:
        """The release report with its act findings carried out: the tag pushed, the release PR opened."""
        wanted = {finding.key: finding for finding in report.findings if finding.verdict is Verdict.ACT}
        carried = {key: await self._run_carry(fleet, key, finding) for key, finding in wanted.items()}
        return restruct(report, findings=tuple(carried.get(finding.key, finding) for finding in report.findings))
