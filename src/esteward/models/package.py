"""Packages pinned in a lockfile and the advisories that concern them."""

from dataclasses import dataclass
from enum import StrEnum, auto


class EcosystemPackage(StrEnum):
    """OSV ecosystem names."""

    PYPI = "PyPI"
    CRATES = "crates.io"


class KindPackage(StrEnum):
    """What an advisory says about a package."""

    VULNERABILITY = auto()
    UNMAINTAINED = auto()


@dataclass(frozen=True, slots=True)
class LockedPackage:
    """One registry package at the exact version a lockfile pins."""

    ecosystem: EcosystemPackage
    name: str
    version: str


@dataclass(frozen=True, slots=True)
class AdvisoryPackage:
    """An advisory affecting a locked package; `fixed` is the first version without it, when one exists."""

    id: str
    package: LockedPackage
    kind: KindPackage
    summary: str
    fixed: str | None
