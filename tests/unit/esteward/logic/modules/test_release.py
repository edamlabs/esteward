"""M3 · release: the policy decides from the records, the module reports the decision and the tag."""

from datetime import datetime

import pytest

from esteward.logic.modules.release import KeyRelease, PlanRelease, ReleaseModule
from esteward.models.fleet import Fleet, ReleaseFleet
from esteward.models.pull import Pull
from esteward.models.report import Report
from esteward.models.verdict import Verdict
from esteward.ops.changelog import Changelog
from esteward.ops.semver import LevelSemver
from tests.unit.esteward.logic.conftest import FakeHost
from tests.unit.esteward.logic.modules.conftest import (
    CHANGELOG_DUE,
    CHANGELOG_EXHAUSTED,
    CHANGELOG_FOLDED,
    MERGE_SHA,
    RELEASE_BRANCH,
    REPO,
    FakeTracker,
    commit_at,
)

SETTINGS = ReleaseFleet()
ADDED = CHANGELOG_DUE.replace("### Fixed", "### Added").replace("- A real bug.", "- A new thing.")
CHANGED = CHANGELOG_DUE.replace("### Fixed", "### Changed")
BREAKING = CHANGELOG_DUE.replace("### Fixed", "### Breaking")
BARE = "# Changelog\n\n## [Unreleased]\n\n### Fixed\n\n- x\n"


async def test_decide_no_changelog(now: datetime) -> None:
    plan = PlanRelease.decide(None, ("v0.1.0",), (), SETTINGS, now)
    assert plan.verdict is Verdict.ESCALATE
    assert plan.reason == "no CHANGELOG.md: the fleet baseline requires one"
    assert plan.tag == "0.1.0"


async def test_decide_no_tag(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGELOG_DUE), (), (), SETTINGS, now)
    assert plan.verdict is Verdict.ESCALATE
    assert plan.folded == "0.1.0"
    assert plan.reason == "no v* tag: the first release is a human decision"


async def test_decide_unversioned(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(BARE), ("v0.1.0",), (commit_at("fix: x", now, 1),), SETTINGS, now)
    assert (plan.verdict, plan.reason) == (Verdict.ESCALATE, "the changelog names no released version")


async def test_decide_untagged(now: datetime) -> None:
    """A version folded but not tagged goes first: the release waits on its own predecessor."""
    plan = PlanRelease.decide(Changelog(CHANGELOG_FOLDED), ("v0.1.0",), (), SETTINGS, now)
    assert plan.verdict is Verdict.WATCH
    assert plan.reason == "v0.1.1 is folded but untagged: that release goes first"


async def test_decide_exhausted(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGELOG_EXHAUSTED), ("v0.1.0",), (), SETTINGS, now)
    assert (plan.verdict, plan.reason, plan.next) == (Verdict.OK, "no unreleased content", None)


@pytest.mark.parametrize(
    ("changelog", "subject"),
    [(CHANGELOG_DUE, "feat!: drop the old surface"), (BREAKING, "chore: tidy")],
    ids=["subject", "section"],
)
async def test_decide_breaking(now: datetime, changelog: str, subject: str) -> None:
    plan = PlanRelease.decide(Changelog(changelog), ("v0.1.0",), (commit_at(subject, now, 30),), SETTINGS, now)
    assert plan.verdict is Verdict.ESCALATE
    assert plan.reason == "breaking change unreleased: a major version is a human decision"


async def test_decide_undated(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGELOG_DUE), ("v0.1.0",), (), SETTINGS, now)
    assert plan.verdict is Verdict.ESCALATE
    assert plan.reason == "unreleased content but no commit since v0.1.0: it cannot be dated"


async def test_decide_fix_releases_at_once(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGELOG_DUE), ("v0.1.0",), (commit_at("fix: a bug", now, 1),), SETTINGS, now)
    assert (plan.verdict, plan.next, plan.level) == (Verdict.ACT, "0.1.1", LevelSemver.PATCH)
    assert plan.reason == "release v0.1.1 (patch): a Fixed or Security entry releases at once"


@pytest.mark.parametrize(
    ("changelog", "subject", "expected"),
    [(ADDED, "docs: a note", "0.2.0"), (CHANGED, "feat: a new thing", "0.2.0")],
    ids=["added-section", "feat-commit"],
)
async def test_decide_minor(now: datetime, changelog: str, subject: str, expected: str) -> None:
    plan = PlanRelease.decide(Changelog(changelog), ("v0.1.0",), (commit_at(subject, now, 30),), SETTINGS, now)
    assert (plan.verdict, plan.next, plan.level) == (Verdict.ACT, expected, LevelSemver.MINOR)
    assert plan.reason == f"release v{expected} (minor): the oldest unreleased commit is 30 days old (> 14)"


async def test_decide_waits(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGED), ("v0.1.0",), (commit_at("docs: a note", now, 2),), SETTINGS, now)
    assert (plan.verdict, plan.next) == (Verdict.OK, None)
    assert plan.reason == "unreleased content waits: the oldest commit is 2 days old (<= 14)"


async def test_decide_aged(now: datetime) -> None:
    plan = PlanRelease.decide(Changelog(CHANGED), ("v0.1.0",), (commit_at("docs: a note", now, 30),), SETTINGS, now)
    assert (plan.verdict, plan.next, plan.level) == (Verdict.ACT, "0.1.1", LevelSemver.PATCH)


async def test_decide_subjects(now: datetime) -> None:
    """The release commits and the merge noise never reach the fold's fallback body."""
    commits = (
        commit_at("chore(release): v0.1.0", now, 3),
        commit_at("Merge pull request #4 from edamlabs/x", now, 2),
        commit_at("fix: a real bug", now, 1),
    )
    assert PlanRelease.decide(Changelog(CHANGELOG_DUE), ("v0.1.0",), commits, SETTINGS, now).subjects == (
        "fix: a real bug",
    )


async def test_run(release_module: ReleaseModule, fleet: Fleet) -> None:
    """The fix entry releases at once, and the folded version already carries its tag."""
    report = await release_module.run(fleet)
    assert [(finding.key, finding.check, finding.verdict) for finding in report.findings] == [
        (KeyRelease.PENDING, "pending", Verdict.ACT),
        (KeyRelease.TAG, "tag", Verdict.OK),
    ]
    assert report.findings[1].detail == "v0.1.0: the tag and the changelog agree"


async def test_run_no_records(release_module: ReleaseModule, release_host: FakeHost, fleet: Fleet) -> None:
    """A repository with neither changelog nor tag escalates both rows, and asks for no commit."""
    release_host.files.clear()
    release_host.tag_list.clear()
    pending, tag = (await release_module.run(fleet)).findings
    assert pending.verdict is Verdict.ESCALATE
    assert tag.detail == "nothing folded and tagged to reconcile yet"


@pytest.mark.parametrize(
    ("merged", "open_pull", "verdict", "detail"),
    [
        (True, False, Verdict.ACT, "tag v0.1.1 pending: release PR #8 merged, the tag is not pushed"),
        (False, True, Verdict.WATCH, "release PR #8 is open"),
        (False, False, Verdict.ESCALATE, "v0.1.1 is folded without an engine release PR: tag it by hand"),
    ],
    ids=["merged", "open", "orphan"],
)
async def test_run_untagged(
    release_module: ReleaseModule,
    release_host: FakeHost,
    tracker: FakeTracker,
    fleet: Fleet,
    merged: bool,
    open_pull: bool,
    verdict: Verdict,
    detail: str,
) -> None:
    """A folded version without its tag: the stage pushes it once its release PR has merged."""
    release_host.files[REPO, "CHANGELOG.md"] = CHANGELOG_FOLDED
    pull = Pull(8, "PR8", RELEASE_BRANCH, "b", False, f"https://gh/{REPO}/pull/8", MERGE_SHA)
    release_host.history[REPO] = ()
    tracker.merged_pulls |= {RELEASE_BRANCH: pull} if merged else {}
    tracker.pulls |= {RELEASE_BRANCH: pull} if open_pull else {}
    pending, tag = (await release_module.run(fleet)).findings
    assert (tag.verdict, tag.detail) == (verdict, detail)
    assert pending.verdict is Verdict.WATCH


async def test_run_reports(now: datetime, release_module: ReleaseModule, fleet: Fleet) -> None:
    report: Report = await release_module.run(fleet)
    assert (report.repo, report.module, report.generated) == (REPO, "release", now)
