"""Pull requests the engine opens, and the operations that carry them."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pull:
    """An open pull request as the tracker returns it."""

    number: int
    node: str
    branch: str
    body: str
    automerge: bool
    url: str


@dataclass(frozen=True, slots=True)
class CreatePull:
    """Open a pull request from a pushed branch, and enable its auto-merge in the same breath."""

    branch: str
    title: str
    body: str


@dataclass(frozen=True, slots=True)
class UpdatePull:
    """Rewrite the body of an open pull request."""

    number: int
    body: str


@dataclass(frozen=True, slots=True)
class AutomergePull:
    """Enable auto-merge on an open pull request that lacks it."""

    node: str


type OperationPull = CreatePull | UpdatePull | AutomergePull
