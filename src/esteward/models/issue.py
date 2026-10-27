"""Tracker issues and the operations esteward applies to them."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class Issue:
    """An open issue as the tracker returns it.

    The triage fields default to the least-privilege values (an insider's, unlabeled, epoch-old issue):
    a construction that omits them is one the community module never touches, while the tracker always
    supplies the real ones.
    """

    number: int
    title: str
    body: str
    author: str = ""
    association: str = "MEMBER"
    labels: tuple[str, ...] = ()
    updated: datetime = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CreateIssue:
    """Open a new issue."""

    title: str
    body: str
    labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UpdateIssue:
    """Rewrite an open issue in place."""

    number: int
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class CloseIssue:
    """Close an issue whose incident is over, with the reason."""

    number: int
    comment: str


@dataclass(frozen=True, slots=True)
class PinIssue:
    """Pin an issue to its repository; applying it to a pinned issue changes nothing."""

    number: int


@dataclass(frozen=True, slots=True)
class LabelIssue:
    """Add and remove labels on one issue."""

    number: int
    add: tuple[str, ...] = ()
    remove: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CommentIssue:
    """Leave one comment on one issue or pull request."""

    number: int
    body: str


type OperationIssue = CreateIssue | UpdateIssue | CloseIssue | PinIssue | LabelIssue | CommentIssue
