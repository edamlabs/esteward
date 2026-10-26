"""Lockfile-only bumps: solver argv, reverse-tree walk, chain rendering."""

from pathlib import Path

import pytest

from esteward.logic.bump import BUMPERS, CargoBump, ChainBump, UvBump
from esteward.models.package import EcosystemPackage, LockedPackage


@pytest.fixture
def crates() -> LockedPackage:
    return LockedPackage(EcosystemPackage.CRATES, "zip", "0.6.6")


@pytest.fixture
def pypi() -> LockedPackage:
    return LockedPackage(EcosystemPackage.PYPI, "urllib3", "1.26.0")


@pytest.mark.parametrize(
    ("lockfile", "manifest"),
    [("Cargo.lock", "Cargo.toml"), ("crates/lib/Cargo.lock", "crates/lib/Cargo.toml")],
    ids=["root", "subdirectory"],
)
async def test_solver_cargo(lockfile: str, manifest: str, crates: LockedPackage) -> None:
    assert CargoBump.solver(lockfile, crates, "9.0.0") == (
        "cargo",
        "update",
        "--manifest-path",
        manifest,
        "-p",
        "zip@0.6.6",
        "--precise",
        "9.0.0",
    )


@pytest.mark.parametrize(
    ("lockfile", "project"),
    [("uv.lock", "."), ("eval/uv.lock", "eval")],
    ids=["root", "subdirectory"],
)
async def test_solver_uv(lockfile: str, project: str, pypi: LockedPackage) -> None:
    assert UvBump.solver(lockfile, pypi, "2.5.0") == (
        "uv",
        "lock",
        "--upgrade-package",
        "urllib3==2.5.0",
        "--project",
        project,
    )


async def test_tree_argv(crates: LockedPackage, pypi: LockedPackage) -> None:
    assert CargoBump.tree("sub/Cargo.lock", crates) == (
        "cargo",
        "tree",
        "-i",
        "zip@0.6.6",
        "--manifest-path",
        "sub/Cargo.toml",
    )
    assert UvBump.tree("uv.lock", pypi) == ("uv", "tree", "--invert", "--package", "urllib3", "--project", ".")


@pytest.mark.parametrize(
    ("fixture", "rendered", "direct"),
    [
        ("cargo-tree-blocked.txt", "zip 0.6.6 ← npyz 0.9.1 ← e-voice-tts", False),
        ("cargo-tree-direct.txt", "figment 0.10.19 ← e-voice-core", True),
        ("cargo-tree-sections.txt", "zip 2.6.1 ← sherpa-onnx-sys 1.13.8 ← sherpa-onnx 1.13.8 ← e-voice-core", False),
        ("uv-tree-blocked.txt", "urllib3 2.8.0 ← requests 2.34.2 ← scratch 0.1.0", False),
        ("uv-tree-direct.txt", "urllib3 1.26.20 ← scratch 0.1.0", True),
    ],
    ids=["cargo-blocked", "cargo-direct", "cargo-sections", "uv-blocked", "uv-direct"],
)
async def test_chain(resources: Path, fixture: str, rendered: str, direct: bool) -> None:
    chain = ChainBump((resources / fixture).read_text(encoding="utf-8"))
    assert chain.render() == rendered
    assert chain.direct() is direct


async def test_chain_empty() -> None:
    assert ChainBump("").walk() == ()


async def test_chain_junk() -> None:
    text = (
        "error: There are multiple `zstd-safe` packages in your project, and the specification `zstd-safe` is ambiguous.\n"
        "Please re-run this command with one of the following specifications:\n"
        "  zstd-safe@5.0.2+zstd.1.5.2\n"
        "  zstd-safe@7.3.0\n"
    )
    assert ChainBump(text).walk() == ()


async def test_chain_stops_at_member(resources: Path) -> None:
    chain = ChainBump((resources / "cargo-tree-blocked.txt").read_text(encoding="utf-8"))
    assert [(node.name, node.member) for node in chain.walk()] == [
        ("zip", False),
        ("npyz", False),
        ("e-voice-tts", True),
    ]


async def test_bumpers(crates: LockedPackage, pypi: LockedPackage) -> None:
    assert BUMPERS[crates.ecosystem] is CargoBump
    assert BUMPERS[pypi.ecosystem] is UvBump
    assert BUMPERS[EcosystemPackage.CRATES].solver("Cargo.lock", crates, "9.0.0")[0] == "cargo"
