"""Raw observations from the outside world, before any verdict."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RepositorySignal:
    """A source repository as its host reports it."""

    slug: str
    archived: bool
    pushed_at: datetime | None
    moved_to: str | None = None


@dataclass(frozen=True, slots=True)
class PackageSignal:
    """The latest release of a package as its registry reports it; `newest` includes prereleases."""

    name: str
    version: str
    released_at: datetime | None
    status: str
    license: str | None
    yanked: bool
    newest: str


@dataclass(frozen=True, slots=True)
class CommitSignal:
    """One commit as its host reports it: the subject line and the moment it landed."""

    subject: str
    committed: datetime
