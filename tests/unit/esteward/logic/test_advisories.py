"""Advisory grouping shared by the deps module and the act stage."""

import pytest

from esteward.logic.advisories import GroupAdvisories
from esteward.models.package import KindPackage
from tests.unit.esteward.logic.conftest import advisory


@pytest.mark.parametrize(
    ("fixes", "expected"),
    [(("2.0.0", "2.10.0", "2.9.1"), "2.10.0"), (("2.0.0", None), None), (("2.0.0", "post-fix"), "post-fix")],
    ids=["highest", "one-unfixed", "unparsable-sorts-last"],
)
async def test_fix(fixes: tuple[str | None, ...], expected: str | None) -> None:
    group = tuple(advisory("p", "1.0", KindPackage.VULNERABILITY, fix, f"A-{i}") for i, fix in enumerate(fixes))
    assert GroupAdvisories(group).fix(group) == expected


async def test_groups() -> None:
    mixed = (
        advisory("b", "1.0", KindPackage.VULNERABILITY, "2.0", "A-2"),
        advisory("a", "1.1", KindPackage.UNMAINTAINED, None, "A-1"),
        advisory("a", "1.0", KindPackage.VULNERABILITY, "2.0", "A-0"),
        advisory("a", "1.0", KindPackage.VULNERABILITY, "2.1", "A-3"),
        advisory("a", "1.0", KindPackage.UNMAINTAINED, None, "A-4"),
    )
    grouped = GroupAdvisories(mixed)
    assert [[a.id for a in group] for group in grouped.groups()] == [["A-4"], ["A-0", "A-3"], ["A-1"], ["A-2"]]
    assert [grouped.fix(group) for group in grouped.groups()] == [None, "2.1", None, "2.0"]
