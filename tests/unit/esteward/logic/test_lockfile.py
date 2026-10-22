"""Lockfiles: only registry packages count."""

from pathlib import Path

import pytest

from esteward.logic.lockfile import parse_lockfile
from esteward.models.package import EcosystemPackage, LockedPackage


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("uv.lock", (LockedPackage(EcosystemPackage.PYPI, "urllib3", "1.26.0"),)),
        ("Cargo.lock", (LockedPackage(EcosystemPackage.CRATES, "atty", "0.2.14"),)),
    ],
    ids=["uv", "cargo"],
)
async def test_parse_lockfile(resources: Path, name: str, expected: tuple[LockedPackage, ...]) -> None:
    assert parse_lockfile(f"sub/dir/{name}", (resources / name).read_text(encoding="utf-8")) == expected


async def test_parse_lockfile_unknown() -> None:
    with pytest.raises(KeyError):
        parse_lockfile("poetry.lock", "")
