"""A fleet entry: `fleet/<repo>.toml`, the maintenance contract of one EDamLabs project."""

from enum import StrEnum, auto
from pathlib import Path
from typing import Self

import msgspec


class KindFleet(StrEnum):
    """What the project ships: a library on PyPI, or a service as a Docker image. Desktop binaries come next."""

    LIB = auto()
    SERVICE = auto()


class FamilyFleet(StrEnum):
    """What the project is: the eager series (EDamLabs' own e- products), a binding of a third-party engine, or the
    organisation's own infrastructure."""

    EAGER = auto()
    BINDING = auto()
    INFRA = auto()


class ModuleFleet(StrEnum):
    """The modules a project enables."""

    DEPS = auto()
    SECURITY = auto()
    DRIFT = auto()
    RELEASE = auto()
    UPSTREAM = auto()
    DOCS = auto()
    COMMUNITY = auto()


class WatchFleet(msgspec.Struct, frozen=True, kw_only=True):
    """A dependency or upstream under watch: its source repository, its registry page, its expected license."""

    name: str
    repo: str | None = None
    registry: str | None = None
    license: str | None = None


class DepsFleet(msgspec.Struct, frozen=True, kw_only=True):
    """Thresholds of the dependency module and what it watches."""

    release_age_days: int = 540
    push_age_days: int = 365
    lockfiles: tuple[str, ...] = ()
    watch: tuple[WatchFleet, ...] = ()


class SecurityFleet(msgspec.Struct, frozen=True, kw_only=True):
    """Where the security module looks for workflow files: path prefixes in the repository."""

    paths: tuple[str, ...] = (".github/workflows",)


class ReleaseFleet(msgspec.Struct, frozen=True, kw_only=True):
    """How long the release policy waits before cutting an ordinary version."""

    unreleased_age_days: int = 14


class EngineFleet(msgspec.Struct, frozen=True, kw_only=True):
    """An upstream engine a binding mirrors: its registry page and the version its API parity was set at."""

    name: str
    registry: str
    parity: str


class UpstreamFleet(msgspec.Struct, frozen=True, kw_only=True):
    """The engines of a binding, as the fleet entry declares them."""

    engines: tuple[EngineFleet, ...] = ()


class DocsFleet(msgspec.Struct, frozen=True, kw_only=True):
    """Which docs checks apply: repositories without a versioned changelog defer the pages check."""

    pages: bool = True


class CommunityFleet(msgspec.Struct, frozen=True, kw_only=True):
    """How long a third-party item may idle before the warning, and before the warning closes it."""

    stale_days: int = 180
    close_days: int = 30


class Fleet(msgspec.Struct, frozen=True, kw_only=True):
    """One project: its repository slug, kind, enabled modules and module settings."""

    repo: str
    kind: KindFleet
    family: FamilyFleet
    modules: tuple[ModuleFleet, ...]
    deps: DepsFleet = DepsFleet()
    security: SecurityFleet = SecurityFleet()
    release: ReleaseFleet = ReleaseFleet()
    upstream: UpstreamFleet = UpstreamFleet()
    docs: DocsFleet = DocsFleet()
    community: CommunityFleet = CommunityFleet()

    @classmethod
    def load(cls, path: Path) -> Self:
        """The fleet entry parsed and validated from its TOML file."""
        return msgspec.toml.decode(path.read_bytes(), type=cls)
