"""In-memory workspace and tracker: the act and release stages are tested without git, tools or network."""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import assert_never

import pytest

from esteward.logic.bump import UvBump
from esteward.logic.modules.act import ActModule
from esteward.logic.modules.release import KeyRelease, ReleaseModule, ReleaseStage
from esteward.models.issue import CloseIssue, CreateIssue, Issue, OperationIssue, PinIssue, UpdateIssue
from esteward.models.outcome import RunOutcome
from esteward.models.package import KindPackage, LockedPackage
from esteward.models.pull import AutomergePull, CreatePull, OperationPull, Pull, UpdatePull
from esteward.models.report import FindingReport, Report
from esteward.models.signal import CommitSignal, PackageSignal
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeAdvisories, FakeHost

BRANCH = "esteward/act/deps-advisory-vulnerability-urllib3-1-26-0"
KEY = "deps:advisory:vulnerability:urllib3@1.26.0"
TITLE = "fix(deps): urllib3 1.26.0 → 2.5.0"
MERGE_SHA = "d" * 40
RELEASE_BRANCH = "esteward/release/v0.1.1"
RELEASE_TITLE = "chore(release): v0.1.1"
REPO = "edamlabs/project"

CHANGELOG_DUE = """# Changelog

## [Unreleased]

### Fixed

- A real bug.

## [0.1.0] — 2026-10-01

First release.
"""
CHANGELOG_FOLDED = """# Changelog

## [Unreleased]

## [0.1.1] — 2026-10-22

### Fixed

- A real bug.

## [0.1.0] — 2026-10-01

First release.
"""
CHANGELOG_EXHAUSTED = """# Changelog

## [Unreleased]

## [0.1.0] — 2026-10-01

First release.
"""
PYPROJECT_STATIC = '[project]\nname = "project"\nversion = "0.1.0"\n'
PYPROJECT_DYNAMIC = '[project]\nname = "project"\ndynamic = ["version"]\n'
CARGO_STATIC = '[package]\nname = "project"\nversion = "0.1.0"\n'


def commit_at(subject: str, now: datetime, days: int) -> CommitSignal:
    """One unreleased commit, `days` before the run's fixed moment."""
    return CommitSignal(subject, now - timedelta(days=days))


@dataclass
class FakeWorkspace:
    """A scripted workspace: `script` answers exact argv, `writes` are the file changes a success applies.

    A write of None deletes the file; `commit_returns` forces the answer of commit; both exist so the
    defensive branches of the act stage are reachable without git.
    """

    base: dict[str, str] = field(default_factory=dict)
    script: dict[tuple[str, ...], RunOutcome] = field(default_factory=dict)
    writes: dict[tuple[str, ...], dict[str, str | None]] = field(default_factory=dict)
    files: dict[str, str] = field(default_factory=dict)
    ran: list[tuple[str, ...]] = field(default_factory=list)
    committed: list[tuple[str, str]] = field(default_factory=list)
    pushed: list[str] = field(default_factory=list)
    tagged: list[tuple[str, str]] = field(default_factory=list)
    checkouts: list[str] = field(default_factory=list)
    restored: int = 0
    dirty: bool = False
    commit_returns: bool | None = None

    async def checkout(self, slug: str) -> None:
        self.checkouts.append(slug)
        self.files = dict(self.base)
        self.dirty = False

    async def run(self, argv: tuple[str, ...]) -> RunOutcome:
        self.ran.append(argv)
        outcome = self.script.get(argv, RunOutcome(0, "", ""))
        match outcome.rc, self.writes.get(argv, {}):
            case 0, writes if writes:
                before = dict(self.files)
                merged = self.files | writes
                self.files = {path: text for path, text in merged.items() if text is not None}
                self.dirty = self.dirty or self.files != before
            case _:
                pass
        return outcome

    async def read(self, path: str) -> str | None:
        return self.files.get(path)

    async def write(self, path: str, text: str) -> None:
        self.files[path] = text
        self.dirty = True

    async def commit(self, branch: str, message: str) -> bool:
        self.committed.append((branch, message))
        changed = self.dirty if self.commit_returns is None else self.commit_returns
        self.dirty = False
        return changed

    async def push(self, branch: str) -> None:
        self.pushed.append(branch)

    async def tag(self, name: str, rev: str) -> None:
        self.tagged.append((name, rev))

    async def restore(self) -> None:
        self.files = dict(self.base)
        self.dirty = False
        self.restored += 1


@dataclass
class FakeTracker:
    """A tracker of open pull requests; creates answer like the real adapter, automerge included.

    `create_forgets` makes a creation vanish: the branch of the act stage that re-reads its own PR.
    """

    pulls: dict[str, Pull] = field(default_factory=dict)
    merged_pulls: dict[str, Pull] = field(default_factory=dict)
    applied: list[OperationIssue | OperationPull] = field(default_factory=list)
    create_forgets: bool = False
    _created: int = field(default=0, init=False)

    async def issues(self, slug: str, label: str) -> tuple[Issue, ...]:
        return ()

    async def pull(self, slug: str, branch: str) -> Pull | None:
        return self.pulls.get(branch)

    async def merged(self, slug: str, branch: str) -> Pull | None:
        return self.merged_pulls.get(branch)

    async def apply(self, slug: str, operation: OperationIssue | OperationPull) -> None:
        self.applied.append(operation)
        match operation:
            case CreatePull(branch=branch, body=body) if not self.create_forgets:
                self._created += 1
                number = 100 + self._created
                self.pulls[branch] = Pull(number, f"PR{number}", branch, body, True, f"https://gh/{slug}/pull/{number}")
            case CreatePull():
                pass
            case UpdatePull(number=number, body=body):
                self.pulls = {
                    branch: replace(pull, body=body) if pull.number == number else pull
                    for branch, pull in self.pulls.items()
                }
            case AutomergePull(node=node):
                self.pulls = {
                    branch: replace(pull, automerge=True) if pull.node == node else pull
                    for branch, pull in self.pulls.items()
                }
            case CreateIssue() | UpdateIssue() | CloseIssue() | PinIssue():
                message = "the act stage never plans issue operations"
                raise AssertionError(message)
            case unreachable:
                assert_never(unreachable)


@pytest.fixture
def act_finding() -> FindingReport:
    """The deps finding of a fixable vulnerability, exactly as the deps module renders it."""
    return FindingReport(
        key=KEY,
        module="deps",
        subject="urllib3 1.26.0",
        check=KindPackage.VULNERABILITY,
        verdict=Verdict.ACT,
        detail="GHSA-x: bad; fixed in 2.5.0",
        url="https://osv.dev/vulnerability/GHSA-x",
    )


@pytest.fixture
def report(now: datetime, act_finding: FindingReport) -> Report:
    return Report(repo="edamlabs/project", module="deps", generated=now, findings=(act_finding,))


@pytest.fixture
def workspace(resources: Path) -> FakeWorkspace:
    """A checkout holding the vulnerable uv.lock of the resource tree."""
    return FakeWorkspace(base={"uv.lock": (resources / "uv.lock").read_text(encoding="utf-8")})


@pytest.fixture
def tracker() -> FakeTracker:
    return FakeTracker()


@pytest.fixture
def act(workspace: FakeWorkspace, advisories: FakeAdvisories, tracker: FakeTracker) -> ActModule:
    return ActModule(workspace, advisories, tracker, publish=True)


@pytest.fixture
def solver(locked: LockedPackage) -> tuple[str, ...]:
    """The exact argv the act stage runs to bump urllib3 to its fix."""
    return UvBump.solver("uv.lock", locked, "2.5.0")


@pytest.fixture
def tree(locked: LockedPackage) -> tuple[str, ...]:
    """The exact argv the act stage runs to ask what depends on urllib3."""
    return UvBump.tree("uv.lock", locked)


@pytest.fixture
def engine_signal() -> Callable[[str], PackageSignal]:
    """Builder of a registry signal for the watched engine, at one newest release."""

    def build(newest: str) -> PackageSignal:
        return PackageSignal(
            "dep", "1.0", released_at=None, status="active", license="MIT", yanked=False, newest=newest
        )

    return build


@pytest.fixture
def fixed_lock(resources: Path) -> str:
    """The uv.lock text with urllib3 at its fix."""
    return (resources / "uv-fixed.lock").read_text(encoding="utf-8")


@pytest.fixture
def release_host(host: FakeHost, now: datetime) -> FakeHost:
    """A host answering the release reads: one tag, one recent fix commit since it."""
    host.files[REPO, "CHANGELOG.md"] = CHANGELOG_DUE
    host.tag_list[REPO] = ("v0.1.0",)
    host.history[REPO] = (CommitSignal("fix: a real bug", now - timedelta(days=2)),)
    return host


@pytest.fixture
def release_module(release_host: FakeHost, tracker: FakeTracker, now: datetime) -> ReleaseModule:
    return ReleaseModule(release_host, tracker, now)


@pytest.fixture
def release_workspace(workspace: FakeWorkspace) -> FakeWorkspace:
    """A checkout holding the due changelog and both static manifests with their locks."""
    workspace.base = {
        "CHANGELOG.md": CHANGELOG_DUE,
        "pyproject.toml": PYPROJECT_STATIC,
        "Cargo.toml": CARGO_STATIC,
        "uv.lock": "version = 1\n",
        "Cargo.lock": "version = 4\n",
    }
    return workspace


@pytest.fixture
def release_stage(
    release_workspace: FakeWorkspace, release_host: FakeHost, tracker: FakeTracker, now: datetime
) -> ReleaseStage:
    return ReleaseStage(release_workspace, release_host, tracker, now, publish=True)


@pytest.fixture
def pending_act() -> FindingReport:
    """The release module's act finding when a version is due."""
    return FindingReport(
        key=KeyRelease.PENDING,
        module="release",
        subject="release",
        check="pending",
        verdict=Verdict.ACT,
        detail="release v0.1.1 (patch): a Fixed or Security entry releases at once",
    )


@pytest.fixture
def tag_act() -> FindingReport:
    """The release module's act finding when a folded version waits for its tag."""
    return FindingReport(
        key=KeyRelease.TAG,
        module="release",
        subject="release",
        check="tag",
        verdict=Verdict.ACT,
        detail="tag v0.1.1 pending: release PR #8 merged, the tag is not pushed",
    )


@pytest.fixture
def release_report(now: datetime, pending_act: FindingReport) -> Report:
    return Report(repo=REPO, module="release", generated=now, findings=(pending_act,))
