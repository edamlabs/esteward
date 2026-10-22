"""What a module run found: the findings of one module on one repository, and their aggregate verdict."""

from datetime import datetime

import msgspec

from esteward.models.verdict import Verdict


class FindingReport(msgspec.Struct, frozen=True, kw_only=True):
    """One observed fact and the verdict it earns; `key` identifies the incident across runs."""

    key: str
    module: str
    subject: str
    check: str
    verdict: Verdict
    detail: str
    url: str | None = None


class Report(msgspec.Struct, frozen=True, kw_only=True):
    """One module on one repository: its findings and when they were observed."""

    repo: str
    module: str
    generated: datetime
    findings: tuple[FindingReport, ...] = ()

    @property
    def verdict(self) -> Verdict:
        """The most severe verdict among the findings; OK when there are none."""
        return max((finding.verdict for finding in self.findings), key=lambda verdict: verdict.rank, default=Verdict.OK)
