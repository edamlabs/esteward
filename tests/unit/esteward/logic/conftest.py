"""In-memory implementations of the core's ports: the core is tested without I/O."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import pytest

from esteward.logic.modules.deps import DepsModule
from esteward.logic.modules.security import SecurityModule
from esteward.models.fleet import DepsFleet, Fleet, KindFleet, ModuleFleet, SecurityFleet, WatchFleet
from esteward.models.package import AdvisoryPackage, EcosystemPackage, KindPackage, LockedPackage
from esteward.models.signal import PackageSignal, RepositorySignal


@dataclass
class FakeHost:
    """A code host backed by dictionaries."""

    repositories: dict[str, RepositorySignal] = field(default_factory=dict)
    files: dict[tuple[str, str], str] = field(default_factory=dict)
    commits: set[tuple[str, str]] = field(default_factory=set)

    async def repository(self, slug: str) -> RepositorySignal | None:
        return self.repositories.get(slug)

    async def file(self, slug: str, path: str) -> str | None:
        return self.files.get((slug, path))

    async def tree(self, slug: str) -> tuple[str, ...]:
        return tuple(path for owner, path in self.files if owner == slug)

    async def commit(self, slug: str, sha: str) -> bool:
        return (slug, sha) in self.commits


@dataclass
class FakeRegistry:
    """A registry backed by a dictionary."""

    packages: dict[str, PackageSignal] = field(default_factory=dict)

    async def package(self, name: str) -> PackageSignal | None:
        return self.packages.get(name)


@dataclass
class FakeAdvisories:
    """An advisory database returning whatever concerns the queried packages."""

    known: tuple[AdvisoryPackage, ...] = ()
    queried: list[tuple[LockedPackage, ...]] = field(default_factory=list)

    async def advisories(self, packages: tuple[LockedPackage, ...]) -> tuple[AdvisoryPackage, ...]:
        self.queried.append(packages)
        return tuple(advisory for advisory in self.known if advisory.package in packages)


@pytest.fixture
def host() -> FakeHost:
    return FakeHost()


@pytest.fixture
def registry() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture
def advisories() -> FakeAdvisories:
    return FakeAdvisories()


@pytest.fixture
def healthy_repository(now: datetime) -> RepositorySignal:
    return RepositorySignal("owner/dep", archived=False, pushed_at=now)


@pytest.fixture
def healthy_package(now: datetime) -> PackageSignal:
    return PackageSignal("dep", "1.0.0", released_at=now, status="active", license="MIT", yanked=False)


@pytest.fixture
def watch() -> WatchFleet:
    return WatchFleet(
        name="dep", repo="https://github.com/owner/dep", registry="https://pypi.org/project/dep/", license="MIT"
    )


@pytest.fixture
def fleet(watch: WatchFleet) -> Fleet:
    return Fleet(
        repo="edamlabs/project",
        kind=KindFleet.LIB,
        modules=(ModuleFleet.DEPS, ModuleFleet.SECURITY),
        deps=DepsFleet(lockfiles=("uv.lock",), watch=(watch,)),
        security=SecurityFleet(),
    )


@pytest.fixture
def locked() -> LockedPackage:
    return LockedPackage(EcosystemPackage.PYPI, "urllib3", "1.26.0")


@pytest.fixture
def advisory_of(locked: LockedPackage) -> Callable[[KindPackage, str | None], AdvisoryPackage]:
    """Builder of an advisory against the locked package."""

    def build(kind: KindPackage, fixed: str | None) -> AdvisoryPackage:
        return AdvisoryPackage(id="GHSA-x", package=locked, kind=kind, summary="bad", fixed=fixed)

    return build


@pytest.fixture
def deps_module(host: FakeHost, registry: FakeRegistry, advisories: FakeAdvisories, now: datetime) -> DepsModule:
    return DepsModule(host, {"pypi.org": registry}, advisories, now)


@pytest.fixture
def security_module(host: FakeHost, now: datetime) -> SecurityModule:
    return SecurityModule(host, now)
