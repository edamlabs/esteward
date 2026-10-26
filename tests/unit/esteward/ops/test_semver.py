"""Semantic versions: the successor of one, the latest of a set."""

import pytest

from esteward.ops.semver import LevelSemver, Semver


@pytest.mark.parametrize(
    ("text", "level", "expected"),
    [
        ("v1.4.2", LevelSemver.PATCH, "1.4.3"),
        ("1.4.2", LevelSemver.MINOR, "1.5.0"),
        ("v0.1.0", LevelSemver.PATCH, "0.1.1"),
        ("v1.3.1.post3", LevelSemver.PATCH, "1.3.2"),
    ],
    ids=["patch-tag", "minor", "patch-zero", "post-release"],
)
async def test_bump(text: str, level: LevelSemver, expected: str) -> None:
    assert Semver(text).bump(level) == expected


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        ((), None),
        (("v0.1.0", "v1.4.2", "v1.3.1.post3"), "v1.4.2"),
        (("0.1.0", "0.2.0"), "0.2.0"),
        (("garbage", "v1.0.0"), "v1.0.0"),
        (("garbage", "junk"), None),
    ],
    ids=["empty", "tags", "headings", "one-parses", "none-parse"],
)
async def test_latest(texts: tuple[str, ...], expected: str | None) -> None:
    assert Semver.latest(texts) == expected
