"""M3 · release stage: the fold, the bump, the locks, the self-merging PR, and the tag of a merged one."""

from datetime import datetime

import pytest

from esteward.logic.modules.release import ReleaseStage
from esteward.models.fleet import Fleet
from esteward.models.outcome import RunOutcome
from esteward.models.pull import AutomergePull, CreatePull, Pull, UpdatePull
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeHost
from tests.unit.esteward.logic.modules.conftest import (
    CHANGELOG_EXHAUSTED,
    CHANGELOG_FOLDED,
    MERGE_SHA,
    PYPROJECT_DYNAMIC,
    RELEASE_BRANCH,
    RELEASE_TITLE,
    REPO,
    FakeTracker,
    FakeWorkspace,
)


async def test_release_publish(
    release_stage: ReleaseStage,
    fleet: Fleet,
    release_report: Report,
    release_workspace: FakeWorkspace,
    tracker: FakeTracker,
    now: datetime,
) -> None:
    """The due release: changelog folded, static versions bumped, locks synced, PR opened, row linked."""
    (finding,) = (await release_stage.run(fleet, release_report)).findings
    assert finding.detail.endswith("[PR #101](https://gh/edamlabs/project/pull/101)")
    assert f"## [0.1.1] — {now:%Y-%m-%d}" in release_workspace.files["CHANGELOG.md"]
    assert 'version = "0.1.1"' in release_workspace.files["pyproject.toml"]
    assert 'version = "0.1.1"' in release_workspace.files["Cargo.toml"]
    assert ("cargo", "update", "--workspace") in release_workspace.ran
    assert ("uv", "lock") in release_workspace.ran
    assert release_workspace.committed == [(RELEASE_BRANCH, RELEASE_TITLE)]
    assert release_workspace.pushed == [RELEASE_BRANCH]
    (created,) = tracker.applied
    assert isinstance(created, CreatePull)
    assert (created.branch, created.title) == (RELEASE_BRANCH, RELEASE_TITLE)
    assert "<!-- esteward:release:v0.1.1 -->" in created.body
    assert "patch release: v0.1.0 → v0.1.1." in created.body
    assert "- A real bug." in created.body


async def test_release_dry(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    """Dry: everything is prepared in the checkout, nothing is committed, pushed or opened."""
    dry = ReleaseStage(release_workspace, release_host, tracker, now, publish=False)
    (finding,) = (await dry.run(fleet, release_report)).findings
    assert finding.detail.endswith("release prepared (dry run)")
    assert "## [0.1.1]" in release_workspace.files["CHANGELOG.md"]
    assert (release_workspace.committed, release_workspace.pushed, tracker.applied) == ([], [], [])


async def test_release_dynamic_manifest(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    """A manifest without a static version is skipped, and no lockfile is re-synced for it."""
    release_workspace.base["pyproject.toml"] = PYPROJECT_DYNAMIC
    del release_workspace.base["Cargo.toml"]
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    (finding,) = (await stage.run(fleet, release_report)).findings
    assert release_workspace.ran == []
    assert release_workspace.files["pyproject.toml"] == PYPROJECT_DYNAMIC
    assert release_workspace.pushed == [RELEASE_BRANCH]
    assert finding.detail.endswith("[PR #101](https://gh/edamlabs/project/pull/101)")


async def test_release_idempotent(
    release_stage: ReleaseStage,
    fleet: Fleet,
    release_report: Report,
    release_workspace: FakeWorkspace,
    tracker: FakeTracker,
) -> None:
    """A second run over the same due release updates nothing: the open PR already says it all."""
    first = await release_stage.run(fleet, release_report)
    second = await release_stage.run(fleet, release_report)
    assert first.findings == second.findings
    assert [type(operation) for operation in tracker.applied] == [CreatePull]
    assert release_workspace.pushed == [RELEASE_BRANCH, RELEASE_BRANCH]


async def test_release_existing_updates(
    release_stage: ReleaseStage,
    fleet: Fleet,
    release_report: Report,
    release_workspace: FakeWorkspace,
    tracker: FakeTracker,
) -> None:
    tracker.pulls[RELEASE_BRANCH] = Pull(7, "PR7", RELEASE_BRANCH, "stale", False, f"https://gh/{REPO}/pull/7")
    (finding,) = (await release_stage.run(fleet, release_report)).findings
    assert [type(operation) for operation in tracker.applied] == [UpdatePull, AutomergePull]
    assert finding.detail.endswith(f"[PR #7](https://gh/{REPO}/pull/7)")


async def test_release_race(
    release_stage: ReleaseStage,
    fleet: Fleet,
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    pending_act: FindingReport,
) -> None:
    """The checkout no longer agrees with the report: the stage opens nothing and the next run decides."""
    release_workspace.base["CHANGELOG.md"] = CHANGELOG_EXHAUSTED
    report = Report(repo=REPO, module="release", generated=now, findings=(pending_act,))
    assert (await release_stage.run(fleet, report)).findings == (pending_act,)
    assert (release_workspace.committed, tracker.applied) == ([], [])


async def test_release_commit_inconsistent(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    """The fold wrote files but git sees no change: an infrastructure fault, raised, never a silent skip."""
    release_workspace.commit_returns = False
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    with pytest.raises(RuntimeError, match="changed nothing"):
        await stage.run(fleet, release_report)


async def test_release_sync_failure(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    """A lockfile sync that fails stops the release before anything is committed."""
    del release_workspace.base["Cargo.lock"]
    release_workspace.script[("uv", "lock")] = RunOutcome(1, "", "boom")
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    with pytest.raises(RuntimeError, match=r"uv lock failed: boom"):
        await stage.run(fleet, release_report)
    assert release_workspace.committed == []


async def test_release_no_changelog(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    release_workspace.base = {}
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    with pytest.raises(RuntimeError, match=r"has no CHANGELOG\.md"):
        await stage.run(fleet, release_report)


async def test_release_created_vanishes(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    release_report: Report,
) -> None:
    tracker.create_forgets = True
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    with pytest.raises(RuntimeError, match="vanished right after creation"):
        await stage.run(fleet, release_report)


async def test_tag_publish(
    release_stage: ReleaseStage,
    fleet: Fleet,
    release_workspace: FakeWorkspace,
    tracker: FakeTracker,
    now: datetime,
    tag_act: FindingReport,
) -> None:
    """The folded version's tag is pushed onto its release PR's merge commit."""
    release_workspace.base = {"CHANGELOG.md": CHANGELOG_FOLDED}
    tracker.merged_pulls[RELEASE_BRANCH] = Pull(
        8, "PR8", RELEASE_BRANCH, "b", False, f"https://gh/{REPO}/pull/8", MERGE_SHA
    )
    report = Report(repo=REPO, module="release", generated=now, findings=(tag_act,))
    (finding,) = (await release_stage.run(fleet, report)).findings
    assert finding.verdict is Verdict.ACT
    assert finding.detail.endswith("tagged v0.1.1")
    assert release_workspace.tagged == [("v0.1.1", MERGE_SHA)]


async def test_tag_dry(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    tag_act: FindingReport,
) -> None:
    release_workspace.base = {"CHANGELOG.md": CHANGELOG_FOLDED}
    tracker.merged_pulls[RELEASE_BRANCH] = Pull(
        8, "PR8", RELEASE_BRANCH, "b", False, f"https://gh/{REPO}/pull/8", MERGE_SHA
    )
    dry = ReleaseStage(release_workspace, release_host, tracker, now, publish=False)
    report = Report(repo=REPO, module="release", generated=now, findings=(tag_act,))
    (finding,) = (await dry.run(fleet, report)).findings
    assert finding.detail.endswith("tag v0.1.1 ready (dry run)")
    assert release_workspace.tagged == []


async def test_tag_unmerged(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    tag_act: FindingReport,
) -> None:
    """The report said merged, the tracker no longer does: a fault, not a silent skip."""
    release_workspace.base = {"CHANGELOG.md": CHANGELOG_FOLDED}
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    report = Report(repo=REPO, module="release", generated=now, findings=(tag_act,))
    with pytest.raises(RuntimeError, match="no longer merged"):
        await stage.run(fleet, report)


async def test_tag_unnamed(
    release_workspace: FakeWorkspace,
    release_host: FakeHost,
    tracker: FakeTracker,
    now: datetime,
    fleet: Fleet,
    tag_act: FindingReport,
) -> None:
    release_workspace.base = {"CHANGELOG.md": "# Changelog\n"}
    stage = ReleaseStage(release_workspace, release_host, tracker, now, publish=True)
    report = Report(repo=REPO, module="release", generated=now, findings=(tag_act,))
    with pytest.raises(RuntimeError, match="names no version"):
        await stage.run(fleet, report)


async def test_skips_without_act(
    release_stage: ReleaseStage, fleet: Fleet, release_workspace: FakeWorkspace, now: datetime
) -> None:
    quiet = Report(repo=REPO, module="release", generated=now, findings=())
    assert await release_stage.run(fleet, quiet) == quiet
    assert release_workspace.checkouts == []


async def test_unknown_key(
    release_stage: ReleaseStage, fleet: Fleet, release_workspace: FakeWorkspace, now: datetime
) -> None:
    foreign = FindingReport(
        key="release:other", module="release", subject="release", check="other", verdict=Verdict.ACT, detail="x"
    )
    report = Report(repo=REPO, module="release", generated=now, findings=(foreign,))
    assert (await release_stage.run(fleet, report)).findings == (foreign,)
    assert release_workspace.checkouts == []
