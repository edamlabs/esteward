"""Lockfile-only bumps: what each ecosystem's solver runs, and what its reverse tree says.

`cargo tree -i` and `uv tree --invert` render the reverse dependency graph with the same glyphs: four
columns per level, `(*)` on a deduplicated subtree, section headers such as `[build-dependencies]`, and a
parenthesised location on a workspace path member. The walk here follows first children from the root and
stops at the first member or leaf: that chain is the evidence a blocked finding carries.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from functools import reduce
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Final

from esteward.models.package import EcosystemPackage, LockedPackage

GLYPHS: Final = "│├└─ "
MEMBER_PREFIXES: Final = ("(/", "(path+file:")
### A chain of root + first dependent means the project itself depends on the package: root, dependent, nothing between.
DIRECT_LEN: Final = 3


@dataclass(frozen=True, slots=True)
class NodeBump:
    """One node of a reverse dependency tree; `member` marks a workspace path member."""

    name: str
    version: str
    depth: int
    member: bool = False


class CargoBump:
    """A lockfile-only bump of a crates.io package by cargo."""

    @staticmethod
    def _common_manifest(lockfile: str) -> str:
        """The workspace manifest beside a lockfile: `sub/Cargo.lock` → `sub/Cargo.toml`."""
        directory = str(PurePosixPath(lockfile).parent)
        return "Cargo.toml" if directory == "." else f"{directory}/Cargo.toml"

    @staticmethod
    def solver(lockfile: str, package: LockedPackage, fix: str) -> tuple[str, ...]:
        """The `cargo update` argv moving one locked version to exactly its fix."""
        return (
            "cargo",
            "update",
            "--manifest-path",
            CargoBump._common_manifest(lockfile),
            "-p",
            f"{package.name}@{package.version}",
            "--precise",
            fix,
        )

    @staticmethod
    def tree(lockfile: str, package: LockedPackage) -> tuple[str, ...]:
        """The `cargo tree -i` argv: what depends on one locked version."""
        return (
            "cargo",
            "tree",
            "-i",
            f"{package.name}@{package.version}",
            "--manifest-path",
            CargoBump._common_manifest(lockfile),
        )


class UvBump:
    """A lockfile-only bump of a PyPI package by uv."""

    @staticmethod
    def _common_project(lockfile: str) -> str:
        """The project directory holding a lockfile: `eval/uv.lock` → `eval`, `uv.lock` → `.`."""
        return str(PurePosixPath(lockfile).parent)

    @staticmethod
    def solver(lockfile: str, package: LockedPackage, fix: str) -> tuple[str, ...]:
        """The `uv lock` argv moving one package to exactly its fix, leaving every other pin alone."""
        return (
            "uv",
            "lock",
            "--upgrade-package",
            f"{package.name}=={fix}",
            "--project",
            UvBump._common_project(lockfile),
        )

    @staticmethod
    def tree(lockfile: str, package: LockedPackage) -> tuple[str, ...]:
        """The `uv tree --invert` argv: what depends on one package; uv rejects a version spec here."""
        return ("uv", "tree", "--invert", "--package", package.name, "--project", UvBump._common_project(lockfile))


BUMPERS: Final[Mapping[EcosystemPackage, type[CargoBump] | type[UvBump]]] = MappingProxyType(
    {EcosystemPackage.CRATES: CargoBump, EcosystemPackage.PYPI: UvBump}
)


def parse_node(line: str) -> NodeBump | None:
    """One tree line as a node; blanks, section headers and prose (errors) are None."""
    content = line.lstrip(GLYPHS)
    depth = (len(line) - len(content)) // 4
    match content.split(" ", 2):
        case [name, version, suffix] if version.startswith("v"):
            return NodeBump(name, version[1:], depth, suffix.startswith(MEMBER_PREFIXES))
        case [name, version] if version.startswith("v"):
            return NodeBump(name, version[1:], depth)
        case _:
            return None


def parse_tree(text: str) -> tuple[NodeBump, ...]:
    """Every node of a reverse dependency tree, in output order."""
    return tuple(node for line in text.splitlines() if (node := parse_node(line)) is not None)


def tree_chain(text: str) -> tuple[NodeBump, ...]:
    """The first-child chain from the root: stops at the first workspace member, else at the first leaf.

    A node at the current depth or above closes the walked subtree; a first occurrence is never
    deduplicated, so the chain followed here is always the fully rendered one.
    """

    def descend(
        state: tuple[tuple[NodeBump, ...], int, bool], node: NodeBump
    ) -> tuple[tuple[NodeBump, ...], int, bool]:
        chain, depth, done = state
        return (
            state
            if done or node.depth <= depth
            else ((*chain, node), node.depth, node.member)
            if node.depth == depth + 1
            else state
        )

    return reduce(descend, parse_tree(text), ((), -1, False))[0]


def render_chain(chain: tuple[NodeBump, ...]) -> str:
    """The chain as status text: `zip 0.6.6 ← npyz 0.9.1 ← e-voice-tts`; a member keeps its name only."""
    return " ← ".join(node.name if node.member else f"{node.name} {node.version}" for node in chain)


def direct_chain(chain: tuple[NodeBump, ...]) -> bool:
    """Whether the project itself is the first dependent: the fix belongs to its manifest, not to upstream."""
    return len(chain) < DIRECT_LEN
