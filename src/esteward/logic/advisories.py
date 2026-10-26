"""Advisory grouping: shared by the deps module that renders findings and the act stage that solves them."""

from itertools import groupby

from packaging.version import InvalidVersion, Version

from esteward.models.package import AdvisoryPackage


def ordered_version(version: str | None) -> tuple[int, Version | str]:
    """Sort key of a version: comparable releases first, unparsable ones after, by text."""
    try:
        return (0, Version(version or ""))
    except InvalidVersion:
        return (1, version or "")


def grouped_fix(advisories: tuple[AdvisoryPackage, ...]) -> str | None:
    """The version that clears every advisory of a group: the highest fix; None when one has no fix."""
    fixes = [advisory.fixed for advisory in advisories]
    return None if None in fixes else max(fixes, key=ordered_version)


def grouped_advisories(advisories: tuple[AdvisoryPackage, ...]) -> tuple[tuple[AdvisoryPackage, ...], ...]:
    """Advisories grouped by package version and kind, in a stable order."""
    ordered = sorted(advisories, key=lambda a: (a.package.name, a.package.version, a.kind, a.id))
    return tuple(tuple(group) for _, group in groupby(ordered, key=lambda a: (a.package, a.kind)))
