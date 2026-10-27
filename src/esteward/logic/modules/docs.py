"""M4 · docs: the documentation of one fleet entry — its build, its deployed pages, its external links.

The strict build runs in a fresh checkout, exactly as the repository's own `make docs` does. The deployed
site is probed where the versions live: the changelog page, which only a fresh deploy carries at the newest
release. External links are checked bounded and deduplicated within the run; a dead link's escalation issue
is the cache across runs, closing itself once the link lives again.
"""

import asyncio
import re
from collections.abc import Mapping
from datetime import datetime
from http import HTTPStatus
from typing import Final

from esteward.logic.ports import HostPort, SitePort, WorkspacePort
from esteward.models.fleet import Fleet
from esteward.models.outcome import RunOutcome
from esteward.models.report import FindingReport, Report
from esteward.models.verdict import Verdict
from esteward.ops.semver import PREFIX, Semver

MODULE: Final = "docs"
### The repository's own docs target: each repo owns its toolchain, all of them build strict.
BUILD: Final = ("make", "docs")
CONFIGS: Final = ("mkdocs.yml", "zensical.toml")
PAGES: Final = ("changelog/", "")
### A dead link is a 404 or a 410; anything else that refuses us (403, 429, 5xx) is not dead, just shy.
DEAD: Final = frozenset({HTTPStatus.NOT_FOUND, HTTPStatus.GONE})
LINK: Final = re.compile(r"\]\((https?://[^)#\s]+)|<(https?://[^>\s]+)>")
EXCERPT: Final = 200
LIMIT: Final = 250


class DocsModule:
    """Documentation health of one fleet entry: build, deployed version, external links."""

    __slots__ = ("_host", "_limit", "_link_limit", "_now", "_site", "_workspace")

    def __init__(
        self,
        host: HostPort,
        site: SitePort,
        workspace: WorkspacePort,
        now: datetime,
        *,
        concurrency: int = 8,
        link_limit: int = LIMIT,
    ) -> None:
        self._host = host
        self._site = site
        self._workspace = workspace
        self._now = now
        self._limit = asyncio.Semaphore(concurrency)
        self._link_limit = link_limit

    ##### PRIVATE #####

    @staticmethod
    def _run_finding(check: str, verdict: Verdict, detail: str, key: str | None = None) -> FindingReport:
        """One docs row."""
        return FindingReport(
            key=key or f"{MODULE}:{check}", module=MODULE, subject="docs", check=check, verdict=verdict, detail=detail
        )

    @staticmethod
    def _run_links(text: str) -> tuple[str, ...]:
        """The external links of one markdown page, in document order."""
        return tuple(markdown or autolink for markdown, autolink in LINK.findall(text))

    async def _run_build(self, fleet: Fleet, tree: tuple[str, ...]) -> FindingReport:
        """The strict build in a fresh checkout; a repository without docs config says so."""
        match next((name for name in CONFIGS if name in tree), None):
            case None:
                return self._run_finding("build", Verdict.WATCH, "no mkdocs.yml or zensical.toml: nothing to build")
            case _:
                await self._workspace.checkout(fleet.repo)
                outcome: RunOutcome = await self._workspace.run(BUILD)
                match outcome.rc:
                    case 0:
                        return self._run_finding("build", Verdict.OK, "zensical build --strict passes on main")
                    case _:
                        excerpt = (outcome.err.strip() or outcome.out.strip())[:EXCERPT]
                        return self._run_finding("build", Verdict.ESCALATE, f"zensical build --strict fails: {excerpt}")

    async def _run_pages(self, fleet: Fleet, tags: tuple[str, ...]) -> FindingReport | None:
        """The deployed pages site: it serves the newest release, or it is stale; None when deferred."""
        match fleet.docs.pages:
            case False:
                return None
            case _:
                owner, name = fleet.repo.split("/", 1)
                root = f"https://{owner}.github.io/{name}/"
                match Semver.latest(tags):
                    case None:
                        return self._run_finding("pages", Verdict.WATCH, f"{root} has no release to serve yet")
                    case tag:
                        latest = tag.removeprefix(PREFIX)
                        match await self._site.status(root):
                            case HTTPStatus.OK:
                                return await self._run_served(root, latest)
                            case status:
                                return self._run_finding(
                                    "pages", Verdict.ESCALATE, f"{root} answers {status}: the pages site is broken"
                                )

    async def _run_served(self, root: str, latest: str) -> FindingReport:
        """The changelog page (or the root, failing that) carries the newest release's version."""
        pages = [(page, await self._site.text(f"{root}{page}")) for page in PAGES]
        served = next((text for _, text in pages if text and latest in text), None)
        match served:
            case None:
                return self._run_finding(
                    "pages", Verdict.ESCALATE, f"{root} does not serve {latest}: the deploy is stale or broken"
                )
            case _:
                return self._run_finding("pages", Verdict.OK, f"{root} serves {latest}")

    async def _run_link(self, url: str, sources: Mapping[str, str]) -> FindingReport | None:
        """One external link: dead escalates with the pages that cite it; anything shy is skipped."""
        async with self._limit:
            status = await self._site.status(url)
        match status:
            case code if code in DEAD:
                citing = ", ".join(path for path, text in sources.items() if url in self._run_links(text))
                return self._run_finding(
                    "link", Verdict.ESCALATE, f"{url} answers {code}; cited by {citing}", key=f"{MODULE}:link:{url}"
                )
            case _:
                ### Live, or shy (403, 429, 5xx): neither is a dead link, and neither fails the run.
                return None

    async def _run_external(self, fleet: Fleet, tree: tuple[str, ...]) -> tuple[FindingReport, ...]:
        """Every external link of the docs tree, bounded and deduplicated within the run."""
        paths = tuple(path for path in tree if path.startswith("docs/") and path.endswith(".md"))
        texts = await asyncio.gather(*(self._host.file(fleet.repo, path) for path in paths))
        sources = {path: text for path, text in zip(paths, texts, strict=True) if text is not None}
        urls = tuple(sorted({url for text in sources.values() for url in self._run_links(text)}))[: self._link_limit]
        found = [
            finding
            for finding in await asyncio.gather(*(self._run_link(url, sources) for url in urls))
            if finding is not None
        ]
        match found:
            case []:
                return (self._run_finding("links", Verdict.OK, f"{len(urls)} external links live"),)
            case _:
                return tuple(found)

    ############################################################

    ##### PUBLIC #####

    async def run(self, fleet: Fleet) -> Report:
        """The docs report of one fleet entry: the build, the deployed version, the external links."""
        tree, tags = await asyncio.gather(self._host.tree(fleet.repo), self._host.tags(fleet.repo))
        build, pages = await asyncio.gather(self._run_build(fleet, tree), self._run_pages(fleet, tags))
        links = await self._run_external(fleet, tree)
        return Report(
            repo=fleet.repo,
            module=MODULE,
            generated=self._now,
            findings=(build, *(() if pages is None else (pages,)), *links),
        )
