"""The status issue and the escalation issues, planned from reports and the open issues."""

from datetime import datetime

import pytest

from esteward.logic.dashboard import DASHBOARD_LABEL, ESCALATION_LABEL, TITLE, StatusDashboard
from esteward.models.issue import CloseIssue, CreateIssue, Issue, PinIssue, UpdateIssue
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict


@pytest.fixture
def dashboard() -> StatusDashboard:
    return StatusDashboard()


@pytest.fixture
def escalated() -> FindingReport:
    return FindingReport(
        key="deps:dep:archived",
        module="deps",
        subject="dep",
        check="archived",
        verdict=Verdict.ESCALATE,
        detail="owner/dep is archived",
        url="https://github.com/owner/dep",
    )


@pytest.fixture
def report(now: datetime, escalated: FindingReport) -> Report:
    ok = FindingReport(
        key="deps:x:healthy", module="deps", subject="x", check="health", verdict=Verdict.OK, detail="healthy"
    )
    return Report(repo="edamlabs/project", module="deps", generated=now, findings=(ok, escalated))


async def test_render(dashboard: StatusDashboard, report: Report) -> None:
    body = dashboard.render((report,))
    assert body.startswith("Maintenance status of **edamlabs/project**, last run 2026-10-22 12:00 UTC.")
    assert "### deps · 🔴 escalate" in body
    assert body.index("| 🔴 escalate | dep |") < body.index("| 🟢 ok | x |")


async def test_render_empty(dashboard: StatusDashboard) -> None:
    assert dashboard.render(()).startswith("🟢 ok")


async def test_plan_first_run(dashboard: StatusDashboard, report: Report) -> None:
    operations = dashboard.plan((report,), (), ())
    assert [type(op) for op in operations] == [CreateIssue, CreateIssue]
    first, second = operations
    assert isinstance(first, CreateIssue)
    assert (first.title, first.labels) == (TITLE, (DASHBOARD_LABEL,))
    assert isinstance(second, CreateIssue)
    assert second.labels == (ESCALATION_LABEL,)
    assert second.body.startswith("<!-- esteward:key=deps:dep:archived -->")


async def test_plan_steady(dashboard: StatusDashboard, report: Report, escalated: FindingReport) -> None:
    status = Issue(1, TITLE, dashboard.render((report,)))
    incident = Issue(2, "esteward · dep: archived", dashboard.plan((report,), (), ())[1].body)  # ty: ignore[unresolved-attribute]
    assert dashboard.plan((report,), (status,), (incident,)) == (PinIssue(1),)


async def test_plan_pins_kept_dashboard(dashboard: StatusDashboard, report: Report) -> None:
    """The status issue is pinned on every run; the adapter skips one that already is."""
    stale = Issue(3, TITLE, "old")
    operations = dashboard.plan((report,), (stale,), ())
    assert operations[:2] == (UpdateIssue(3, TITLE, dashboard.render((report,))), PinIssue(3))


async def test_plan_changes(dashboard: StatusDashboard, report: Report, now: datetime) -> None:
    stale_status = Issue(1, TITLE, "old")
    stale_incident = Issue(2, "esteward · dep: archived", "<!-- esteward:key=deps:dep:archived -->\nold")
    cleared = Issue(3, "esteward · gone: archived", "<!-- esteward:key=deps:gone:archived -->\nold")
    other_module = Issue(4, "esteward · pin", "<!-- esteward:key=security:pin:a@b -->\nold")
    unmarked = Issue(5, "manual", "no marker")
    operations = dashboard.plan((report,), (stale_status,), (stale_incident, cleared, other_module, unmarked))
    assert [(type(op).__name__, getattr(op, "number", None)) for op in operations] == [
        ("UpdateIssue", 1),
        ("PinIssue", 1),
        ("UpdateIssue", 2),
        ("CloseIssue", 3),
    ]
    assert isinstance(operations[3], CloseIssue)
    assert isinstance(operations[0], UpdateIssue)


async def test_plan_converges(dashboard: StatusDashboard, report: Report) -> None:
    body = dashboard.render((report,))
    incident = dashboard.plan((report,), (), ())[1]
    assert isinstance(incident, CreateIssue)
    statuses = (Issue(14, TITLE, body), Issue(13, TITLE, body))
    incidents = (Issue(21, incident.title, incident.body), Issue(20, incident.title, incident.body))
    operations = dashboard.plan((report,), statuses, incidents)
    assert operations == (
        PinIssue(13),
        CloseIssue(14, "esteward: duplicate of #13."),
        CloseIssue(21, "esteward: duplicate of #20."),
    )
