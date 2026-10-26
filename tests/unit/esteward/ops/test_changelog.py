"""Keep-a-Changelog documents: the unreleased section, the latest version, the release fold."""

from pathlib import Path

import pytest

from esteward.ops.changelog import Changelog


@pytest.fixture
def curated(resources: Path) -> Changelog:
    return Changelog((resources / "changelog-unreleased.md").read_text(encoding="utf-8"))


@pytest.fixture
def exhausted(resources: Path) -> Changelog:
    return Changelog((resources / "changelog-empty.md").read_text(encoding="utf-8"))


async def test_unreleased_curated(curated: Changelog) -> None:
    section = curated.unreleased()
    assert "### Added" in section
    assert "- A new endpoint." in section
    assert not [line for line in section if line.startswith("## [")]


async def test_unreleased_exhausted(exhausted: Changelog) -> None:
    assert exhausted.unreleased() == ()


async def test_unreleased_absent() -> None:
    bare = Changelog("# Changelog\n\nSome prose.\n")
    assert bare.unreleased() == ()
    assert bare.sections() == frozenset()


async def test_sections(curated: Changelog) -> None:
    assert curated.sections() == frozenset({"Added", "Fixed"})


async def test_latest(exhausted: Changelog) -> None:
    """Both date styles parse: `-` in the bindings, `—` in the eager series."""
    assert exhausted.latest() == "0.1.1"


async def test_latest_none() -> None:
    assert Changelog("# Changelog\n\n## [Unreleased]\n").latest() is None


async def test_fold_curated(curated: Changelog, resources: Path) -> None:
    """The curated notes become the body, byte for byte the fold of e-serde's release workflow."""
    folded = curated.fold("0.2.0", "2026-11-02", ("ignored: the notes are already curated",))
    assert folded == (resources / "changelog-folded-curated.md").read_text(encoding="utf-8")


async def test_fold_commits(exhausted: Changelog, resources: Path) -> None:
    """With no curated notes, the commit subjects become the body."""
    folded = exhausted.fold("0.2.0", "2026-11-02", ("fix: a real bug", "docs: the readme"))
    assert folded == (resources / "changelog-folded-commits.md").read_text(encoding="utf-8")


async def test_fold_absent_unreleased() -> None:
    with pytest.raises(ValueError, match=r"no ## \[Unreleased\]"):
        Changelog("# Changelog\n").fold("0.2.0", "2026-11-02", ())
