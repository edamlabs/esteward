"""Tracker issues and the operations esteward applies to them."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Issue:
    """An open issue as the tracker returns it."""

    number: int
    title: str
    body: str


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


type OperationIssue = CreateIssue | UpdateIssue | CloseIssue
