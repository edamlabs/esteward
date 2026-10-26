"""L1 · act: lockfile-only bumps executed, blocked upstream watched, manifest changes escalated."""

from collections.abc import Callable
from pathlib import Path

import pytest
from msgspec.structs import replace as restruct

from esteward.logic.bump import UvBump
from esteward.logic.modules.act import ActModule
from esteward.models.fleet import Fleet
from esteward.models.outcome import RunOutcome
from esteward.models.package import AdvisoryPackage, KindPackage, LockedPackage
from esteward.models.pull import AutomergePull, CreatePull, Pull, UpdatePull
from esteward.models.report import Report
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeAdvisories
from tests.unit.esteward.logic.modules.conftest import BRANCH, KEY, TITLE, FakeTracker, FakeWorkspace


async def test_run_publishes(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.ACT
    assert finding.detail.endswith("[PR #101](https://gh/edamlabs/project/pull/101)")
    assert finding.url == "https://osv.dev/vulnerability/GHSA-x"
    assert workspace.committed == [(BRANCH, TITLE)]
    assert workspace.pushed == [BRANCH]
    assert workspace.restored == 1
    (created,) = tracker.applied
    assert isinstance(created, CreatePull)
    assert (created.branch, created.title) == (BRANCH, TITLE)
    assert f"<!-- esteward:key={KEY} -->" in created.body
    assert "`uv.lock` → `2.5.0`" in created.body
    assert "1 advisory: GHSA-x" in created.body


async def test_run_dry(
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    dry = ActModule(workspace, advisories, tracker, publish=False)
    (finding,) = (await dry.run(fleet, report)).findings
    assert finding.verdict is Verdict.ACT
    assert finding.detail.endswith("bump verified (dry run)")
    assert (workspace.committed, workspace.pushed, tracker.applied) == ([], [], [])
    assert workspace.restored == 1


async def test_run_idempotent(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    """A second run over the same finding updates nothing: the open PR already says it all."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    first = (await act.run(fleet, report)).findings[0]
    second = (await act.run(fleet, report)).findings[0]
    assert first == second
    assert [type(operation) for operation in tracker.applied] == [CreatePull]
    assert workspace.pushed == [BRANCH, BRANCH]
    assert workspace.restored == 2


async def test_run_existing_updates(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    tracker.pulls[BRANCH] = Pull(7, "PR7", BRANCH, "stale", False, "https://gh/edamlabs/project/pull/7")
    (finding,) = (await act.run(fleet, report)).findings
    assert [type(operation) for operation in tracker.applied] == [UpdatePull, AutomergePull]
    assert finding.detail.endswith("[PR #7](https://gh/edamlabs/project/pull/7)")


async def test_run_blocked(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    resources: Path,
    solver: tuple[str, ...],
    tree: tuple[str, ...],
) -> None:
    """A fix an intermediate package blocks is watched, with the chain that proves it."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.script[solver] = RunOutcome(1, "", "error: no resolution")
    workspace.script[tree] = RunOutcome(0, (resources / "uv-tree-blocked.txt").read_text(encoding="utf-8"), "")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.WATCH
    assert finding.key == KEY
    assert finding.detail.endswith("blocked upstream: urllib3 2.8.0 ← requests 2.34.2 ← scratch 0.1.0")
    assert (workspace.committed, workspace.pushed, tracker.applied) == ([], [], [])
    assert workspace.restored == 1


async def test_run_manifest(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    resources: Path,
    solver: tuple[str, ...],
    tree: tuple[str, ...],
) -> None:
    """A fix only the project's own manifest blocks is a human's call."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.script[solver] = RunOutcome(1, "", "error: pinned by the project")
    workspace.script[tree] = RunOutcome(0, (resources / "uv-tree-direct.txt").read_text(encoding="utf-8"), "")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.ESCALATE
    assert finding.detail.endswith("the fix needs a manifest change: urllib3 1.26.20 ← scratch 0.1.0")


async def test_run_solver_without_tree(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    solver: tuple[str, ...],
    tree: tuple[str, ...],
) -> None:
    """No chain, no story: the solver's own first line is the evidence, and a human reads it."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.script[solver] = RunOutcome(101, "", "")
    workspace.script[tree] = RunOutcome(101, "", "error: no such subcommand\nsecond line")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.ESCALATE
    assert "the solver cannot reach 2.5.0: the solver failed with rc 101" in finding.detail


async def test_run_stuck_reason_excerpted(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    solver: tuple[str, ...],
    tree: tuple[str, ...],
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.script[solver] = RunOutcome(101, "", "error: first line\nnoise\nmore noise")
    workspace.script[tree] = RunOutcome(101, "", "")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.detail.endswith("the solver cannot reach 2.5.0: error: first line")


async def test_run_unverified(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    resources: Path,
    tree: tuple[str, ...],
) -> None:
    """A solver that reports success without moving the lockfile is answered by the chain."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.script[tree] = RunOutcome(0, (resources / "uv-tree-blocked.txt").read_text(encoding="utf-8"), "")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.WATCH
    assert "blocked upstream" in finding.detail


async def test_run_lockfile_vanished(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    solver: tuple[str, ...],
    tree: tuple[str, ...],
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": None}
    workspace.script[tree] = RunOutcome(1, "", "")
    (finding,) = (await act.run(fleet, report)).findings
    assert finding.verdict is Verdict.ESCALATE
    assert "uv.lock vanished after the solver ran" in finding.detail


async def test_run_skips_without_act_findings(
    act: ActModule, fleet: Fleet, report: Report, workspace: FakeWorkspace, now: object
) -> None:
    quiet = restruct(report, findings=tuple(f for f in report.findings if f.verdict is Verdict.OK))
    assert await act.run(fleet, quiet) == quiet
    assert workspace.checkouts == []


async def test_run_skips_unmatched(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    resources: Path,
) -> None:
    """The checkout already carries the fix: nothing to solve, the report passes through."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.base = {"uv.lock": (resources / "uv-fixed.lock").read_text(encoding="utf-8")}
    assert (await act.run(fleet, report)).findings == report.findings
    assert workspace.checkouts == ["edamlabs/project"]
    assert (workspace.committed, tracker.applied) == ([], [])


async def test_run_missing_lockfile(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    workspace: FakeWorkspace,
) -> None:
    """A lockfile the fleet names but the checkout lacks is skipped, not an error."""
    workspace.base = {}
    assert (await act.run(fleet, report)).findings == report.findings
    assert advisories.queried == [()]


async def test_run_unfixable_skipped(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    locked: LockedPackage,
    workspace: FakeWorkspace,
) -> None:
    """A group where one advisory has no fix stays the deps module's escalation: act cannot solve it."""
    advisories.known = (
        AdvisoryPackage(id="GHSA-x", package=locked, kind=KindPackage.VULNERABILITY, summary="bad", fixed="2.5.0"),
        AdvisoryPackage(id="GHSA-y", package=locked, kind=KindPackage.VULNERABILITY, summary="worse", fixed=None),
    )
    assert (await act.run(fleet, report)).findings == report.findings
    assert workspace.checkouts == ["edamlabs/project"]


async def test_run_multiple_lockfiles(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    locked: LockedPackage,
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    fixed_lock: str,
) -> None:
    """One finding key spanning two lockfiles: one commit, one branch, one PR listing both bumps."""
    advisories.known = tuple(
        AdvisoryPackage(id=f"GHSA-{i}", package=locked, kind=KindPackage.VULNERABILITY, summary="bad", fixed="2.5.0")
        for i in range(6)
    )
    double = restruct(fleet, deps=restruct(fleet.deps, lockfiles=("uv.lock", "eval/uv.lock")))
    workspace.base |= {"eval/uv.lock": workspace.base["uv.lock"]}
    root, nested = UvBump.solver("uv.lock", locked, "2.5.0"), UvBump.solver("eval/uv.lock", locked, "2.5.0")
    workspace.writes[root] = {"uv.lock": fixed_lock}
    workspace.writes[nested] = {"eval/uv.lock": fixed_lock}
    (finding,) = (await act.run(double, report)).findings
    assert finding.detail.endswith("[PR #101](https://gh/edamlabs/project/pull/101)")
    assert workspace.committed == [(BRANCH, TITLE)]
    assert workspace.pushed == [BRANCH]
    (created,) = tracker.applied
    assert isinstance(created, CreatePull)
    assert "6 advisories: GHSA-0, GHSA-1, GHSA-2, GHSA-3, GHSA-4 …" in created.body
    assert "`uv.lock` → `2.5.0`" in created.body
    assert "`eval/uv.lock` → `2.5.0`" in created.body
    assert advisories.queried[0] == (locked,)


async def test_run_mixed_lockfiles(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    locked: LockedPackage,
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    resources: Path,
    fixed_lock: str,
) -> None:
    """One lockfile bumps, the other is blocked: the PR carries the bump, the finding reports the block."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    double = restruct(fleet, deps=restruct(fleet.deps, lockfiles=("uv.lock", "eval/uv.lock")))
    workspace.base |= {"eval/uv.lock": workspace.base["uv.lock"]}
    workspace.writes[UvBump.solver("uv.lock", locked, "2.5.0")] = {"uv.lock": fixed_lock}
    workspace.script[UvBump.solver("eval/uv.lock", locked, "2.5.0")] = RunOutcome(1, "", "error: pinned by eval")
    workspace.script[UvBump.tree("eval/uv.lock", locked)] = RunOutcome(
        0, (resources / "uv-tree-blocked.txt").read_text(encoding="utf-8"), ""
    )
    (finding,) = (await act.run(double, report)).findings
    assert finding.verdict is Verdict.WATCH
    assert finding.detail.endswith(
        "blocked upstream: urllib3 2.8.0 ← requests 2.34.2 ← scratch 0.1.0 · [PR #101](https://gh/edamlabs/project/pull/101)"
    )
    assert workspace.pushed == [BRANCH]
    assert [type(operation) for operation in tracker.applied] == [CreatePull]


async def test_run_mixed_dry(
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    locked: LockedPackage,
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    resources: Path,
    fixed_lock: str,
) -> None:
    """Dry and partially blocked: the chain is the story, no PR is mentioned."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    double = restruct(fleet, deps=restruct(fleet.deps, lockfiles=("uv.lock", "eval/uv.lock")))
    workspace.base |= {"eval/uv.lock": workspace.base["uv.lock"]}
    workspace.writes[UvBump.solver("uv.lock", locked, "2.5.0")] = {"uv.lock": fixed_lock}
    workspace.script[UvBump.solver("eval/uv.lock", locked, "2.5.0")] = RunOutcome(1, "", "error: pinned by eval")
    workspace.script[UvBump.tree("eval/uv.lock", locked)] = RunOutcome(
        0, (resources / "uv-tree-blocked.txt").read_text(encoding="utf-8"), ""
    )
    dry = ActModule(workspace, advisories, tracker, publish=False)
    (finding,) = (await dry.run(double, report)).findings
    assert finding.verdict is Verdict.WATCH
    assert finding.detail.endswith("blocked upstream: urllib3 2.8.0 ← requests 2.34.2 ← scratch 0.1.0")
    assert (workspace.pushed, tracker.applied) == ([], [])


async def test_run_commit_inconsistent(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    """The solver verified but git sees no change: an infrastructure fault, raised, never a silent skip."""
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    workspace.commit_returns = False
    with pytest.raises(RuntimeError, match="shows no change"):
        await act.run(fleet, report)


async def test_run_created_pull_vanishes(
    act: ActModule,
    fleet: Fleet,
    report: Report,
    advisories: FakeAdvisories,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    workspace: FakeWorkspace,
    tracker: FakeTracker,
    solver: tuple[str, ...],
    fixed_lock: str,
) -> None:
    advisories.known = (advisory_of(KindPackage.VULNERABILITY, "2.5.0"),)
    workspace.writes[solver] = {"uv.lock": fixed_lock}
    tracker.create_forgets = True
    with pytest.raises(RuntimeError, match="vanished right after creation"):
        await act.run(fleet, report)
