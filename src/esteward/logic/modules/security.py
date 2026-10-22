"""M6 · security: every action a workflow pins by commit SHA must resolve to a real commit.

Workflow files live under configurable paths (`.github/workflows` by default; template repos add their fragments).
A pin that names no commit fails at `uses:` resolution, and a lookalike SHA is how a supply-chain swap hides.
zizmor and gitleaks already run in each project's own hooks; this module checks what they cannot: the pins exist.
"""

import asyncio
import re
from datetime import datetime
from typing import Final

from esteward.logic.ports import HostPort
from esteward.models.fleet import Fleet
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict

MODULE: Final = "security"
PIN: Final = re.compile(r"uses:\s*['\"]?([\w.-]+/[\w.-]+)(?:/[^@\s'\"]*)?@([0-9a-f]{40})\b")


class SecurityModule:
    """Workflow pin integrity of one fleet entry."""

    __slots__ = ("_host", "_limit", "_now")

    def __init__(self, host: HostPort, now: datetime, concurrency: int = 8) -> None:
        self._host = host
        self._now = now
        self._limit = asyncio.Semaphore(concurrency)

    ##### PRIVATE #####

    async def _run_pins(self, fleet: Fleet) -> tuple[tuple[str, str], ...]:
        """Every `(action, sha)` pinned across the YAML files under the configured paths, once each."""
        paths = tuple(
            path
            for path in await self._host.tree(fleet.repo)
            if path.endswith((".yml", ".yaml")) and path.startswith(fleet.security.paths)
        )
        texts = await asyncio.gather(*(self._host.file(fleet.repo, path) for path in paths))
        return tuple(dict.fromkeys(pin for text in texts if text is not None for pin in PIN.findall(text)))

    async def _run_resolve(self, action: str, sha: str) -> tuple[str, str, bool]:
        """Whether the pinned commit exists in the action's repository."""
        async with self._limit:
            return action, sha, await self._host.commit(action, sha)

    def _run_finding(self, action: str, sha: str, *, exists: bool) -> FindingReport:
        """A resolved pin is OK; a phantom one escalates, it breaks every run that uses it."""
        return FindingReport(
            key=f"{MODULE}:pin:{action}@{sha}",
            module=MODULE,
            subject=action,
            check="pin",
            verdict=Verdict.OK if exists else Verdict.ESCALATE,
            detail=f"{sha[:12]} {'resolves' if exists else 'names no commit'}",
            url=f"https://github.com/{action}/commit/{sha}",
        )

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The security report of a fleet entry: one finding per distinct pinned action commit."""
        resolved = await asyncio.gather(
            *(self._run_resolve(action, sha) for action, sha in await self._run_pins(fleet))
        )
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=tuple(self._run_finding(action, sha, exists=exists) for action, sha, exists in resolved),
        )
