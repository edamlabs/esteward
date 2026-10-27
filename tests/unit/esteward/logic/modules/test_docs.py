"""M4 · docs: the strict build, the deployed version, and the external links of the docs tree."""

from datetime import datetime

import pytest
from msgspec.structs import replace as restruct

from esteward.logic.modules.docs import BUILD, DocsModule
from esteward.models.fleet import DocsFleet, Fleet
from esteward.models.outcome import RunOutcome
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeHost, FakeSite
from tests.unit.esteward.logic.modules.conftest import FakeWorkspace

SITE = "https://edamlabs.github.io/project/"
INDEX = "# Title\n\nSee [the engine](https://engine.example/docs) and <https://engine.example/raw>.\n"


@pytest.fixture
def docs_host(host: FakeHost) -> FakeHost:
    """A repository tree with a docs config, one page, and a tag."""
    host.files["edamlabs/project", "mkdocs.yml"] = "site_name: project\n"
    host.files["edamlabs/project", "docs/index.md"] = INDEX
    host.files["edamlabs/project", "docs/changelog.md"] = "# Changelog\n\n## [0.1.0] — 2026-10-01\n"
    host.tag_list["edamlabs/project"] = ("v0.1.0",)
    return host


@pytest.fixture
def docs_module(docs_host: FakeHost, site: FakeSite, workspace: FakeWorkspace, now: datetime) -> DocsModule:
    return DocsModule(docs_host, site, workspace, now, link_limit=10)


async def test_run_all_green(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    site.texts[f"{SITE}changelog/"] = "# Changelog\n\n## [0.1.0] — 2026-10-01\n"
    report = await docs_module.run(fleet)
    assert [(f.check, f.verdict) for f in report.findings] == [
        ("build", Verdict.OK),
        ("pages", Verdict.OK),
        ("links", Verdict.OK),
    ]
    assert report.findings[2].detail == "2 external links live"


async def test_run_build_fails(docs_module: DocsModule, fleet: Fleet, workspace: FakeWorkspace, site: FakeSite) -> None:
    workspace.script[BUILD] = RunOutcome(1, "", "ERROR - doc page missing: index.md")
    site.texts[f"{SITE}changelog/"] = "## [0.1.0]"
    (build, _, _) = (await docs_module.run(fleet)).findings
    assert build.verdict is Verdict.ESCALATE
    assert "zensical build --strict fails: ERROR" in build.detail


async def test_run_build_without_config(
    docs_module: DocsModule, fleet: Fleet, docs_host: FakeHost, workspace: FakeWorkspace, site: FakeSite
) -> None:
    del docs_host.files["edamlabs/project", "mkdocs.yml"]
    site.texts[f"{SITE}changelog/"] = "## [0.1.0]"
    (build, _, _) = (await docs_module.run(fleet)).findings
    assert build.verdict is Verdict.WATCH
    assert workspace.checkouts == []


async def test_run_pages_stale(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    site.texts[f"{SITE}changelog/"] = "# Changelog\n\n## [0.0.9] — old\n"
    site.texts[SITE] = "home"
    (_, pages, _) = (await docs_module.run(fleet)).findings
    assert pages.verdict is Verdict.ESCALATE
    assert f"{SITE} does not serve 0.1.0" in pages.detail


async def test_run_pages_broken(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    site.statuses[SITE] = 404
    (_, pages, _) = (await docs_module.run(fleet)).findings
    assert pages.verdict is Verdict.ESCALATE
    assert f"{SITE} answers 404" in pages.detail


async def test_run_pages_no_release(docs_module: DocsModule, fleet: Fleet, docs_host: FakeHost, site: FakeSite) -> None:
    docs_host.tag_list.clear()
    (_, pages, _) = (await docs_module.run(fleet)).findings
    assert pages.verdict is Verdict.WATCH
    assert "has no release to serve yet" in pages.detail


async def test_run_pages_deferred(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    """A repository whose versions live per image defers the pages check to its release policy."""
    deferred = restruct(fleet, docs=DocsFleet(pages=False))
    findings = (await docs_module.run(deferred)).findings
    assert [f.check for f in findings] == ["build", "links"]
    assert not [url for url in site.asked if "github.io" in url]


async def test_run_dead_link(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    site.texts[f"{SITE}changelog/"] = "## [0.1.0]"
    site.statuses["https://engine.example/docs"] = 404
    findings = (await docs_module.run(fleet)).findings
    (dead,) = [f for f in findings if f.check == "link"]
    assert dead.verdict is Verdict.ESCALATE
    assert dead.key == "docs:link:https://engine.example/docs"
    assert dead.detail == "https://engine.example/docs answers 404; cited by docs/index.md"
    assert not [f for f in findings if f.check == "links"]


async def test_run_shy_link_is_skipped(docs_module: DocsModule, fleet: Fleet, site: FakeSite) -> None:
    site.texts[f"{SITE}changelog/"] = "## [0.1.0]"
    site.statuses["https://engine.example/docs"] = 429
    (_, _, links) = (await docs_module.run(fleet)).findings
    assert (links.check, links.verdict) == ("links", Verdict.OK)


async def test_run_links_bounded(
    docs_host: FakeHost, site: FakeSite, workspace: FakeWorkspace, now: datetime, fleet: Fleet
) -> None:
    """The bound is deterministic: sorted URLs, first `link_limit` checked, the rest wait their run."""
    docs_host.files["edamlabs/project", "docs/index.md"] = (
        INDEX + "\n[a](https://b.example/x)\n[b](https://a.example/x)\n[c](https://c.example/x)\n"
    )
    module = DocsModule(docs_host, site, workspace, now, link_limit=3)
    site.texts[f"{SITE}changelog/"] = "## [0.1.0]"
    await module.run(fleet)
    checked = [url for url in site.asked if "github.io" not in url]
    assert checked == ["https://a.example/x", "https://b.example/x", "https://c.example/x"]
