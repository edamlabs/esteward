"""M5 · community: third-party triage decided from the records, applied when publishing."""

from datetime import datetime, timedelta

import pytest

from esteward.logic.modules.community import CommunityModule, CommunityStage
from esteward.models.fleet import Fleet
from esteward.models.issue import Issue, LabelIssue
from esteward.models.pull import TriagePull
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.modules.conftest import FakeTracker


@pytest.fixture
def community_module(tracker: FakeTracker, now: datetime) -> CommunityModule:
    return CommunityModule(tracker, now)


@pytest.fixture
def outsider(now: datetime) -> Issue:
    """A third-party issue, fresh and with a reproduction: only the community label is missing."""
    return Issue(3, "a bug", "repro inside", author="stranger", association="NONE", updated=now - timedelta(days=1))


async def test_run_insiders_untouched(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_issues_list = [Issue(1, "own", "x", author="damien", association="OWNER", updated=now)]
    report = await community_module.run(fleet)
    assert [(f.check, f.verdict, f.detail) for f in report.findings] == [
        ("open", Verdict.OK, "0 open third-party items, 0 needing triage")
    ]


async def test_run_labels_the_stranger(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, outsider: Issue
) -> None:
    tracker.open_issues_list = [outsider]
    report = await community_module.run(fleet)
    (finding, summary) = report.findings
    assert (finding.key, finding.verdict, finding.detail) == ("community:issue:3", Verdict.ACT, "labeled community")
    assert summary.detail == "1 open third-party items, 1 needing triage"


async def test_run_asks_the_missing_repro(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_issues_list = [
        Issue(4, "broken", "", author="stranger", association="CONTRIBUTOR", updated=now - timedelta(days=2))
    ]
    (finding, _) = (await community_module.run(fleet)).findings
    assert finding.detail == "labeled community; asked for a reproduction"


async def test_run_marks_stale(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_issues_list = [
        Issue(5, "old", "repro", author="stranger", association="NONE", updated=now - timedelta(days=200))
    ]
    (finding, _) = (await community_module.run(fleet)).findings
    assert finding.detail == "labeled community; marked stale"


async def test_run_closes_stale(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_issues_list = [
        Issue(
            6,
            "older",
            "repro",
            author="stranger",
            association="NONE",
            labels=("community", "stale"),
            updated=now - timedelta(days=220),
        )
    ]
    (finding, _) = (await community_module.run(fleet)).findings
    assert finding.detail == "closed stale"


async def test_run_unmarks_stale(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_issues_list = [
        Issue(
            7,
            "alive again",
            "repro",
            author="stranger",
            association="NONE",
            labels=("community", "stale"),
            updated=now - timedelta(days=1),
        )
    ]
    (finding, _) = (await community_module.run(fleet)).findings
    assert finding.detail == "unmarked stale"


async def test_run_holds_the_warning(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    """Marked stale, idle past the stale age but not past the warning's own age: nothing to say again."""
    tracker.open_issues_list = [
        Issue(
            12,
            "waiting",
            "repro",
            author="stranger",
            association="NONE",
            labels=("community", "stale"),
            updated=now - timedelta(days=200),
        )
    ]
    report = await community_module.run(fleet)
    assert [(f.check, f.verdict, f.detail) for f in report.findings] == [
        ("open", Verdict.OK, "1 open third-party items, 0 needing triage")
    ]


async def test_run_triages_pulls(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    tracker.open_pulls_list = [
        TriagePull(
            number=8,
            author="stranger",
            association="NONE",
            labels=(),
            updated=now - timedelta(days=200),
            draft=False,
        )
    ]
    (finding, _) = (await community_module.run(fleet)).findings
    assert (finding.key, finding.detail) == ("community:pull:8", "labeled community; marked stale")


async def test_run_ignores_drafts(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    """A draft is work its author marked unfinished: nothing is said about it, however idle it sits."""
    tracker.open_pulls_list = [
        TriagePull(
            number=11,
            author="stranger",
            association="NONE",
            labels=(),
            updated=now - timedelta(days=400),
            draft=True,
        )
    ]
    report = await community_module.run(fleet)
    assert [(f.check, f.verdict, f.detail) for f in report.findings] == [
        ("open", Verdict.OK, "1 open third-party items, 0 needing triage")
    ]


async def test_run_ignores_automation(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime
) -> None:
    """The engine's own status issue and Renovate's answer as NONE/CONTRIBUTOR: their login is the record."""
    tracker.open_issues_list = [
        Issue(
            number=13,
            title="esteward · maintenance status",
            body="the dashboard",
            author="eself-maintenance[bot]",
            association="NONE",
            updated=now - timedelta(days=400),
        ),
        Issue(
            number=2,
            title="dependency update",
            body="bump urllib3",
            author="renovate[bot]",
            association="CONTRIBUTOR",
            updated=now - timedelta(days=400),
        ),
    ]
    report = await community_module.run(fleet)
    assert [(f.check, f.verdict, f.detail) for f in report.findings] == [
        ("open", Verdict.OK, "0 open third-party items, 0 needing triage")
    ]


async def test_stage_applies(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime, outsider: Issue
) -> None:
    tracker.open_issues_list = [outsider]
    report = await community_module.run(fleet)
    stage = CommunityStage(tracker, now, publish=True)
    (finding, _) = (await stage.run(fleet, report)).findings
    assert finding.detail == "labeled community · applied"
    assert tracker.applied == [LabelIssue(3, add=("community",))]


async def test_stage_dry(
    community_module: CommunityModule, tracker: FakeTracker, fleet: Fleet, now: datetime, outsider: Issue
) -> None:
    tracker.open_issues_list = [outsider]
    report = await community_module.run(fleet)
    stage = CommunityStage(tracker, now, publish=False)
    (finding, _) = (await stage.run(fleet, report)).findings
    assert finding.detail == "labeled community · planned (dry run)"
    assert tracker.applied == []
