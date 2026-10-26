"""Advisory grouping shared by the deps module and the act stage."""

import pytest
from packaging.version import Version

from esteward.logic.advisories import grouped_advisories, grouped_fix, ordered_version
from esteward.models.package import AdvisoryPackage, EcosystemPackage, KindPackage, LockedPackage


def advisory(name: str, version: str, kind: KindPackage, fixed: str | None, advisory_id: str) -> AdvisoryPackage:
    """One advisory against one locked package."""
    return AdvisoryPackage(
        id=advisory_id,
        package=LockedPackage(EcosystemPackage.PYPI, name, version),
        kind=kind,
        summary="s",
        fixed=fixed,
    )


@pytest.mark.parametrize(
    ("version", "expected"),
    [("2.0.0", (0, Version("2.0.0"))), (None, (1, "")), ("post-fix", (1, "post-fix"))],
    ids=["comparable", "missing", "unparsable"],
)
async def test_ordered_version(version: str | None, expected: tuple[int, object]) -> None:
    assert ordered_version(version) == expected


async def test_ordered_version_comparable_before_unparsable() -> None:
    assert ordered_version("9.0.0")[0] < ordered_version("post-fix")[0]


@pytest.mark.parametrize(
    ("fixes", "expected"),
    [(("2.0.0", "2.10.0", "2.9.1"), "2.10.0"), (("2.0.0", None), None), (("2.0.0", "post-fix"), "post-fix")],
    ids=["highest", "one-unfixed", "unparsable-wins-as-text"],
)
async def test_grouped_fix(fixes: tuple[str | None, ...], expected: str | None) -> None:
    group = tuple(advisory("p", "1.0", KindPackage.VULNERABILITY, fix, f"A-{i}") for i, fix in enumerate(fixes))
    assert grouped_fix(group) == expected


async def test_grouped_advisories() -> None:
    mixed = (
        advisory("b", "1.0", KindPackage.VULNERABILITY, "2.0", "A-2"),
        advisory("a", "1.1", KindPackage.UNMAINTAINED, None, "A-1"),
        advisory("a", "1.0", KindPackage.VULNERABILITY, "2.0", "A-0"),
        advisory("a", "1.0", KindPackage.VULNERABILITY, "2.1", "A-3"),
        advisory("a", "1.0", KindPackage.UNMAINTAINED, None, "A-4"),
    )
    groups = grouped_advisories(mixed)
    assert [[a.id for a in group] for group in groups] == [["A-4"], ["A-0", "A-3"], ["A-1"], ["A-2"]]
    assert [grouped_fix(group) for group in groups] == [None, "2.1", None, "2.0"]
