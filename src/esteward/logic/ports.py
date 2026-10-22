"""The interfaces the core needs from the world; adapters satisfy them structurally."""

from typing import Protocol, runtime_checkable

from esteward.models.issue import Issue, OperationIssue
from esteward.models.package import AdvisoryPackage, LockedPackage
from esteward.models.signal import PackageSignal, RepositorySignal


@runtime_checkable
class HostPort(Protocol):
    """A code host: repositories, their files and commits."""

    async def repository(self, slug: str) -> RepositorySignal | None: ...

    async def file(self, slug: str, path: str) -> str | None: ...

    async def tree(self, slug: str) -> tuple[str, ...]: ...

    async def commit(self, slug: str, sha: str) -> bool: ...


@runtime_checkable
class RegistryPort(Protocol):
    """A package registry: the latest release of a package."""

    async def package(self, name: str) -> PackageSignal | None: ...


@runtime_checkable
class AdvisoryPort(Protocol):
    """An advisory database: what is known against exact package versions."""

    async def advisories(self, packages: tuple[LockedPackage, ...]) -> tuple[AdvisoryPackage, ...]: ...


@runtime_checkable
class TrackerPort(Protocol):
    """An issue tracker: open issues by label, and the operations that change them."""

    async def issues(self, slug: str, label: str) -> tuple[Issue, ...]: ...

    async def apply(self, slug: str, operation: OperationIssue) -> None: ...
