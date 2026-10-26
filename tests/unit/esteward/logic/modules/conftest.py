"""In-memory workspace and tracker: the act stage is tested without git, tools or network."""

from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import assert_never

import pytest

from esteward.logic.bump import UvBump
from esteward.logic.modules.act import ActModule
from esteward.models.issue import CloseIssue, CreateIssue, Issue, OperationIssue, PinIssue, UpdateIssue
from esteward.models.outcome import RunOutcome
from esteward.models.package import KindPackage, LockedPackage
from esteward.models.pull import AutomergePull, CreatePull, OperationPull, Pull, UpdatePull
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeAdvisories

BRANCH = "esteward/act/deps-advisory-vulnerability-urllib3-1-26-0"
KEY = "deps:advisory:vulnerability:urllib3@1.26.0"
TITLE = "fix(deps): urllib3 1.26.0 → 2.5.0"


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

    async def commit(self, branch: str, message: str) -> bool:
        self.committed.append((branch, message))
        changed = self.dirty if self.commit_returns is None else self.commit_returns
        self.dirty = False
        return changed

    async def push(self, branch: str) -> None:
        self.pushed.append(branch)

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
    applied: list[OperationIssue | OperationPull] = field(default_factory=list)
    create_forgets: bool = False
    _created: int = field(default=0, init=False)

    async def issues(self, slug: str, label: str) -> tuple[Issue, ...]:
        return ()

    async def pull(self, slug: str, branch: str) -> Pull | None:
        return self.pulls.get(branch)

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
def fixed_lock(resources: Path) -> str:
    """The uv.lock text with urllib3 at its fix."""
    return (resources / "uv-fixed.lock").read_text(encoding="utf-8")
