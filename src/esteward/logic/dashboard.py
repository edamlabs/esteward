"""The single status issue and one issue per escalated incident, planned as operations, never applied here.

The dashboard is rewritten in place on every run. An escalation issue carries its finding key in a marker,
so the next run updates it while the finding persists and closes it once the finding is gone.
"""

import re
from collections.abc import Iterable
from typing import Final

from esteward.models.issue import CloseIssue, CreateIssue, Issue, OperationIssue, UpdateIssue
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

DASHBOARD_LABEL: Final = "esteward"
ESCALATION_LABEL: Final = "esteward-escalation"
TITLE: Final = "esteward · maintenance status"
KEY: Final = re.compile(r"<!-- esteward:key=(\S+) -->")
ICONS: Final = {Verdict.OK: "🟢", Verdict.WATCH: "🔵", Verdict.ACT: "🟡", Verdict.ESCALATE: "🔴"}


class StatusDashboard:
    """Renders the status issue and plans the escalation issues of one repository."""

    __slots__ = ()

    ##### PRIVATE #####

    @staticmethod
    def _render_section(report: Report) -> str:
        """One module: its verdict, then one row per finding, most severe first."""
        rows = "".join(
            f"| {ICONS[f.verdict]} {f.verdict} | {f.subject} | {f.check} | {f.detail} |\n"
            for f in sorted(report.findings, key=lambda f: (-f.verdict.rank, f.subject, f.check))
        )
        return (
            f"### {report.module} · {ICONS[report.verdict]} {report.verdict}\n\n"
            f"| Verdict | Subject | Check | Detail |\n|---|---|---|---|\n{rows}"
        )

    @staticmethod
    def _plan_body(finding: FindingReport) -> str:
        """An escalation issue: the finding, its evidence, and the marker that ties it to its key."""
        evidence = f"\n**Evidence:** {finding.url}\n" if finding.url else ""
        return (
            f"<!-- esteward:key={finding.key} -->\n"
            f"**{finding.subject}** · `{finding.module}` · {finding.check}\n\n{finding.detail}\n{evidence}\n"
            "_Opened by esteward; it closes itself when the finding clears._\n"
        )

    @staticmethod
    def _plan_title(finding: FindingReport) -> str:
        return f"esteward · {finding.subject}: {finding.check}"

    def _plan_dashboard(self, reports: Iterable[Report], current: tuple[Issue, ...]) -> tuple[OperationIssue, ...]:
        """Rewrite the status issue, or open it on the first run."""
        body = self.render(reports)
        match current:
            case ():
                return (CreateIssue(TITLE, body, (DASHBOARD_LABEL,)),)
            case (issue, *_) if issue.body != body:
                return (UpdateIssue(issue.number, TITLE, body),)
            case _:
                return ()

    def _plan_escalations(self, reports: tuple[Report, ...], current: tuple[Issue, ...]) -> tuple[OperationIssue, ...]:
        """Open new incidents, refresh lasting ones, close the ones that cleared in the modules that ran."""
        wanted = {f.key: f for r in reports for f in r.findings if f.verdict is Verdict.ESCALATE}
        existing = {match[1]: issue for issue in current if (match := KEY.search(issue.body))}
        ran = {r.module for r in reports}
        opened = tuple(
            CreateIssue(self._plan_title(f), self._plan_body(f), (ESCALATION_LABEL,))
            for key, f in sorted(wanted.items())
            if key not in existing
        )
        refreshed = tuple(
            UpdateIssue(existing[key].number, self._plan_title(f), body)
            for key, f in sorted(wanted.items())
            if key in existing and existing[key].body != (body := self._plan_body(f))
        )
        closed = tuple(
            CloseIssue(issue.number, "esteward: the finding cleared on the last run.")
            for key, issue in sorted(existing.items())
            if key not in wanted and key.split(":", 1)[0] in ran
        )
        return opened + refreshed + closed

    ############################################################

    ##### PUBLIC #####

    def render(self, reports: Iterable[Report]) -> str:
        """The status issue body: one section per module, in module order."""
        ordered = sorted(reports, key=lambda r: r.module)
        stamp = max((r.generated for r in ordered), default=None)
        head = (
            f"Maintenance status of **{ordered[0].repo}**, last run {stamp:%Y-%m-%d %H:%M} UTC.\n\n" if ordered else ""
        )
        legend = "🟢 ok · 🔵 watch · 🟡 act · 🔴 escalate (one issue per incident)\n\n"
        return head + legend + "\n".join(self._render_section(r) for r in ordered)

    def plan(
        self, reports: tuple[Report, ...], dashboard: tuple[Issue, ...], escalations: tuple[Issue, ...]
    ) -> tuple[OperationIssue, ...]:
        """Every tracker operation this run calls for: the dashboard first, then the incidents."""
        return self._plan_dashboard(reports, dashboard) + self._plan_escalations(reports, escalations)
