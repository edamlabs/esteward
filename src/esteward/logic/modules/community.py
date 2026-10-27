"""M5 · community: deterministic triage of third-party issues and pull requests.

A label marks what the engine has seen; an empty issue earns a request for the reproduction it lacks;
idleness past the fleet's age earns a warning, and idleness past the warning closes the item with a
message. Only a stranger is triaged: an insider writes with commit rights, automation (the engine's own
status issues, Renovate) is not a stranger, and a draft is work its author marked unfinished. The engine
never approves and never merges a third-party pull request: no such operation exists in its vocabulary.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum, auto
from typing import Final

from msgspec.structs import replace as restruct

from esteward.logic.ports import TrackerPort
from esteward.models.fleet import CommunityFleet, Fleet
from esteward.models.issue import CloseIssue, CommentIssue, Issue, LabelIssue, OperationIssue
from esteward.models.pull import TriagePull
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

MODULE: Final = "community"
COMMUNITY: Final = "community"
STALE: Final = "stale"
REPRO: Final = "needs-repro"
### Everyone else writes to the repository with commit rights; triage is for the rest.
INSIDERS: Final = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
### Measured 2026-10-27: an app-authenticated actor (the engine's own status issues, Renovate) answers as
### CONTRIBUTOR or NONE, never as a bot. Its login suffix is the record that says what it is.
AUTOMATION: Final = "[bot]"
REPRO_ASK: Final = (
    "esteward here, the maintenance engine of this organisation. This issue has no reproduction yet: "
    "a minimal snippet with its input and the expected versus observed output is what lets anyone pick "
    "it up. Added, it moves; without it, it will go stale like every unreproducible report."
)
STALE_WARN: Final = (
    "esteward here: no activity for a while, so this goes stale. It closes in {close} days without a "
    "reply; anything new reopens the conversation and drops the label."
)
STALE_CLOSE: Final = "esteward: closed after {idle} days without activity, stale warning unanswered."


class KindCommunity(StrEnum):
    """What a triaged item is: an issue, whose missing body asks for a reproduction, or a pull request."""

    ISSUE = auto()
    PULL = auto()


@dataclass(frozen=True, slots=True)
class TaskCommunity:
    """One triage decision: the item it concerns, the operations it earns, and the row it becomes."""

    kind: KindCommunity
    number: int
    ops: tuple[OperationIssue, ...]
    detail: str


class PlanCommunity:
    """The triage plan of one repository's open items, decided from who wrote them and how idle they are."""

    __slots__ = ("_now", "_settings")

    def __init__(self, settings: CommunityFleet, now: datetime) -> None:
        self._settings = settings
        self._now = now

    ##### PRIVATE #####

    @staticmethod
    def _decide_face(item: Issue | TriagePull) -> tuple[KindCommunity, str]:
        """What the item is and the body its reproduction check reads."""
        ### Only an issue has a body to reproduce in: a pull request is triaged for idleness alone.
        match item:
            case Issue(body=body):
                return KindCommunity.ISSUE, body
            case _:
                return KindCommunity.PULL, ""

    def _decide_idle(
        self, number: int, labels: tuple[str, ...], updated: datetime
    ) -> tuple[str, tuple[OperationIssue, ...]]:
        """The stale lifecycle as its detail and operations: warn past the stale age, close past the warning,
        unmark on new activity; no detail and no operations while it is neither idle enough nor marked."""
        idle = (self._now - updated).days
        match STALE in labels, idle:
            case False, _ if idle > self._settings.stale_days:
                return "marked stale", (
                    LabelIssue(number, add=(STALE,)),
                    CommentIssue(number, STALE_WARN.format(close=self._settings.close_days)),
                )
            case True, _ if idle > self._settings.stale_days + self._settings.close_days:
                return "closed stale", (CloseIssue(number, STALE_CLOSE.format(idle=idle)),)
            case True, _ if idle <= self._settings.stale_days:
                return "unmarked stale", (LabelIssue(number, remove=(STALE,)),)
            ### Marked and idle between the two ages: the warning stands, nothing to say again.
            case _:
                return "", ()

    def _decide_item(self, item: Issue | TriagePull) -> TaskCommunity | None:
        """One open item: the operations its state earns, or None when the engine has nothing to say."""
        match item:
            ### A draft is work its author marked unfinished: it stays counted, it is not spoken about.
            case TriagePull(draft=True):
                return None
            case _ if not PlanCommunity.outsider(item):
                return None
        kind, body = self._decide_face(item)
        rows = (
            ("labeled community", () if COMMUNITY in item.labels else (LabelIssue(item.number, add=(COMMUNITY,)),)),
            (
                "asked for a reproduction",
                (CommentIssue(item.number, REPRO_ASK), LabelIssue(item.number, add=(REPRO,)))
                if kind is KindCommunity.ISSUE and not body.strip() and REPRO not in item.labels
                else (),
            ),
            self._decide_idle(item.number, item.labels, item.updated),
        )
        ops = tuple(operation for _, row_ops in rows for operation in row_ops)
        detail = "; ".join(part for part, row_ops in rows if row_ops)
        return TaskCommunity(kind, item.number, ops, detail) if ops else None

    ############################################################

    ##### PUBLIC #####

    @staticmethod
    def outsider(item: Issue | TriagePull) -> bool:
        """Whether a stranger owns the conversation: insiders write with commit rights, and automation answers
        as CONTRIBUTOR or NONE, which is why the login and not the association is the record of what it is."""
        return item.association not in INSIDERS and not item.author.endswith(AUTOMATION)

    @classmethod
    def decide(
        cls, issues: tuple[Issue, ...], pulls: tuple[TriagePull, ...], settings: CommunityFleet, now: datetime
    ) -> tuple[TaskCommunity, ...]:
        """Every triage decision of one repository's open items: the issues, then the pull requests."""
        plan = cls(settings, now)
        return tuple(task for task in (plan._decide_item(item) for item in (*issues, *pulls)) if task is not None)


class CommunityModule:
    """The community report of one fleet entry: one triage row per item that needs one, and the count."""

    __slots__ = ("_now", "_tracker")

    def __init__(self, tracker: TrackerPort, now: datetime) -> None:
        self._tracker = tracker
        self._now = now

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """Every open third-party issue and pull request, triaged by the records alone."""
        issues, pulls = await asyncio.gather(
            self._tracker.open_issues(fleet.repo), self._tracker.open_pulls(fleet.repo)
        )
        tasks = PlanCommunity.decide(issues, pulls, fleet.community, self._now)
        third = sum(1 for item in (*issues, *pulls) if PlanCommunity.outsider(item))
        summary = FindingReport(
            key=f"{MODULE}:open",
            module=MODULE,
            subject="community",
            check="open",
            verdict=Verdict.OK,
            detail=f"{third} open third-party items, {len(tasks)} needing triage",
        )
        findings = tuple(
            FindingReport(
                key=f"{MODULE}:{task.kind}:{task.number}",
                module=MODULE,
                subject=f"{task.kind} #{task.number}",
                check="triage",
                verdict=Verdict.ACT,
                detail=task.detail,
            )
            for task in tasks
        )
        return Report(repo=fleet.repo, module=MODULE, generated=self._now, findings=(*findings, summary))


class CommunityStage:
    """The triage carried out: every planned operation applied when publishing, and the rows saying so."""

    __slots__ = ("_now", "_publish", "_tracker")

    def __init__(self, tracker: TrackerPort, now: datetime, *, publish: bool = False) -> None:
        self._tracker = tracker
        self._now = now
        self._publish = publish

    ##### PUBLIC #####

    async def run(self, fleet: Fleet, report: Report) -> Report:
        """The community report with its triage rows carried out or marked as planned."""
        issues, pulls = await asyncio.gather(
            self._tracker.open_issues(fleet.repo), self._tracker.open_pulls(fleet.repo)
        )
        tasks = {
            f"{MODULE}:{task.kind}:{task.number}": task
            for task in PlanCommunity.decide(issues, pulls, fleet.community, self._now)
        }
        planned = tuple(task.ops for task in tasks.values()) if self._publish else ()
        await asyncio.gather(*(self._tracker.apply(fleet.repo, operation) for ops in planned for operation in ops))
        suffix = " · applied" if self._publish else " · planned (dry run)"
        return restruct(
            report,
            findings=tuple(
                restruct(finding, detail=f"{finding.detail}{suffix}") if finding.key in tasks else finding
                for finding in report.findings
            ),
        )
