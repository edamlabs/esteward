"""Advisory grouping: shared by the deps module that renders findings and the act stage that solves them."""

from itertools import groupby

from packaging.version import InvalidVersion, Version

from esteward.models.package import AdvisoryPackage


class GroupAdvisories:
    """One advisory set: grouped by package version and kind, each group with the fix that clears it."""

    __slots__ = ("_groups",)

    def __init__(self, advisories: tuple[AdvisoryPackage, ...]) -> None:
        ordered = sorted(advisories, key=lambda a: (a.package.name, a.package.version, a.kind, a.id))
        self._groups = tuple(tuple(group) for _, group in groupby(ordered, key=lambda a: (a.package, a.kind)))

    ##### PRIVATE #####

    @staticmethod
    def _fix_ordered(version: str | None) -> tuple[int, Version | str]:
        """Sort key of a version: comparable releases first, unparsable ones after, by text."""
        try:
            return (0, Version(version or ""))
        except InvalidVersion:
            return (1, version or "")

    ############################################################

    ##### PUBLIC #####

    def groups(self) -> tuple[tuple[AdvisoryPackage, ...], ...]:
        """The groups by package version and kind, in a stable order."""
        return self._groups

    def fix(self, group: tuple[AdvisoryPackage, ...]) -> str | None:
        """The version that clears every advisory of one group: the highest fix; None when one has no fix."""
        fixes = [advisory.fixed for advisory in group]
        return None if None in fixes else max(fixes, key=GroupAdvisories._fix_ordered)
