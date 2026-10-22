"""M1 · deps: verdicts from watched signals and from advisories on locked packages."""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from msgspec.structs import replace as restruct

from esteward.logic.modules.deps import DepsModule
from esteward.models.fleet import Fleet, WatchFleet
from esteward.models.package import AdvisoryPackage, KindPackage
from esteward.models.signal import PackageSignal, RepositorySignal
from esteward.models.verdict import Verdict
from tests.unit.esteward.logic.conftest import FakeAdvisories, FakeHost, FakeRegistry


async def test_run_healthy(
    host: FakeHost,
    registry: FakeRegistry,
    advisories: FakeAdvisories,
    deps_module: DepsModule,
    fleet: Fleet,
    healthy_repository: RepositorySignal,
    healthy_package: PackageSignal,
) -> None:
    host.repositories["owner/dep"] = healthy_repository
    registry.packages["dep"] = healthy_package
    report = await deps_module.run(fleet)
    assert [(f.subject, f.check, f.verdict) for f in report.findings] == [("dep", "health", Verdict.OK)]
    assert report.verdict is Verdict.OK


@pytest.mark.parametrize(
    ("repository", "package", "expected"),
    [
        ({"archived": True}, {}, {("archived", Verdict.ESCALATE)}),
        ({"pushed_at": datetime(2025, 9, 1, tzinfo=UTC)}, {}, {("dormant", Verdict.WATCH)}),
        ({}, {"status": "archived"}, {("status", Verdict.ESCALATE)}),
        ({}, {"status": "quarantined"}, {("status", Verdict.ESCALATE)}),
        ({}, {"released_at": datetime(2025, 3, 1, tzinfo=UTC)}, {("stale", Verdict.WATCH)}),
        ({}, {"yanked": True}, {("yanked", Verdict.WATCH)}),
        ({}, {"license": "GPL-3.0"}, {("license", Verdict.ESCALATE)}),
        ({"pushed_at": None}, {"released_at": None}, {("health", Verdict.OK)}),
    ],
    ids=["archived", "dormant", "pep792-archived", "pep792-quarantined", "stale", "yanked", "license", "unknown-dates"],
)
async def test_run_rules(
    host: FakeHost,
    registry: FakeRegistry,
    advisories: FakeAdvisories,
    deps_module: DepsModule,
    fleet: Fleet,
    healthy_repository: RepositorySignal,
    healthy_package: PackageSignal,
    repository: dict[str, object],
    package: dict[str, object],
    expected: set[tuple[str, Verdict]],
) -> None:
    host.repositories["owner/dep"] = replace(healthy_repository, **repository)
    registry.packages["dep"] = replace(healthy_package, **package)
    report = await deps_module.run(fleet)
    assert {(f.check, f.verdict) for f in report.findings} == expected


@pytest.mark.parametrize("missing", ["repository", "package"], ids=["repository", "package"])
async def test_run_vanished(
    host: FakeHost,
    registry: FakeRegistry,
    advisories: FakeAdvisories,
    deps_module: DepsModule,
    fleet: Fleet,
    healthy_repository: RepositorySignal,
    healthy_package: PackageSignal,
    missing: str,
) -> None:
    host.repositories |= {} if missing == "repository" else {"owner/dep": healthy_repository}
    registry.packages |= {} if missing == "package" else {"dep": healthy_package}
    report = await deps_module.run(fleet)
    assert [(f.check, f.verdict, f.key.rsplit(":", 1)[-1]) for f in report.findings] == [
        ("vanished", Verdict.ESCALATE, missing)
    ]


async def test_run_unwatched_sources(
    host: FakeHost, advisories: FakeAdvisories, deps_module: DepsModule, fleet: Fleet
) -> None:
    bare = restruct(fleet, deps=restruct(fleet.deps, watch=(WatchFleet(name="bare"),)))
    report = await deps_module.run(bare)
    assert [(f.subject, f.verdict) for f in report.findings] == [("bare", Verdict.OK)]


@pytest.mark.parametrize(
    ("kind", "fixed", "verdict"),
    [
        (KindPackage.VULNERABILITY, "2.0.0", Verdict.ACT),
        (KindPackage.VULNERABILITY, None, Verdict.ESCALATE),
        (KindPackage.UNMAINTAINED, None, Verdict.WATCH),
    ],
    ids=["fixable", "unfixable", "unmaintained"],
)
async def test_run_advisories(
    host: FakeHost,
    registry: FakeRegistry,
    advisories: FakeAdvisories,
    deps_module: DepsModule,
    fleet: Fleet,
    resources: Path,
    advisory_of: Callable[[KindPackage, str | None], AdvisoryPackage],
    kind: KindPackage,
    fixed: str | None,
    verdict: Verdict,
) -> None:
    bare = restruct(fleet, deps=restruct(fleet.deps, watch=()))
    host.files["edamlabs/project", "uv.lock"] = (resources / "uv.lock").read_text(encoding="utf-8")
    advisories.known = (advisory_of(kind, fixed),)
    report = await deps_module.run(bare)
    assert [(f.subject, f.verdict) for f in report.findings] == [("urllib3 1.26.0", verdict)]
    assert [p.name for p in advisories.queried[0]] == ["urllib3"]


async def test_run_missing_lockfile(
    host: FakeHost, advisories: FakeAdvisories, deps_module: DepsModule, fleet: Fleet
) -> None:
    bare = restruct(fleet, deps=restruct(fleet.deps, watch=()))
    report = await deps_module.run(bare)
    assert report.findings == ()
    assert advisories.queried == [()]
