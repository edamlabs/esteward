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
    def _latest_version(text: str) -> Version:
        """The parsed version of a tag or heading text, its `v` prefix stripped."""
        return Version(text.removeprefix(PREFIX))

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
    def rank(text: str) -> tuple[int, Version | str]:
        """Sort key of a version text: parseable releases first, unparsable ones after, by text."""
        try:
            return (0, Version(text.removeprefix(PREFIX)))
        except InvalidVersion:
            return (1, text)

    @staticmethod
    def latest(texts: tuple[str, ...]) -> str | None:
        """The highest of the parseable version texts, prefix optional; None when none parses."""
        match [text for text in texts if Semver.rank(text)[0] == 0]:
            case []:
                return None
            case parseable:
                return max(parseable, key=Semver._latest_version)
