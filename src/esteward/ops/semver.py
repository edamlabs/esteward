"""Semantic versions: the successor of one, the latest of a set."""

from enum import StrEnum, auto
from typing import Final, assert_never

from packaging.version import InvalidVersion, Version

PREFIX: Final = "v"


class LevelSemver(StrEnum):
    """The bump a release can carry: a major version is always a human's decision."""

    PATCH = auto()
    MINOR = auto()


class Semver:
    """One semantic version, its `v` prefix optional."""

    __slots__ = ("_version",)

    def __init__(self, text: str) -> None:
        self._version = Version(text.removeprefix(PREFIX))

    ##### PRIVATE #####

    @staticmethod
    def _latest_rank(text: str) -> tuple[int, Version | str]:
        """Sort key of a version text: parseable releases above, unparsable below, by text."""
        try:
            return (1, Version(text.removeprefix(PREFIX)))
        except InvalidVersion:
            return (0, text)

    ############################################################

    ##### PUBLIC #####

    def bump(self, level: LevelSemver) -> str:
        """The next version at one level, without prefix."""
        match level:
            case LevelSemver.MINOR:
                return f"{self._version.major}.{self._version.minor + 1}.0"
            case LevelSemver.PATCH:
                return f"{self._version.major}.{self._version.minor}.{self._version.micro + 1}"
            case unreachable:
                assert_never(unreachable)

    @staticmethod
    def latest(texts: tuple[str, ...]) -> str | None:
        """The highest of the version texts, prefix optional; None when none of them parses."""
        match max(((Semver._latest_rank(text), text) for text in texts), default=None):
            case None:
                return None
            case ((1, _), text):
                return text
            case _:
                return None
