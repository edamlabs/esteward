"""Lockfiles parsed into the registry packages they pin; path, git and workspace members are not registry packages."""

import tomllib
from collections.abc import Callable, Mapping
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Final

from esteward.models.package import EcosystemPackage, LockedPackage

CRATES_INDEX: Final = frozenset(
    {
        "registry+https://github.com/rust-lang/crates.io-index",
        "sparse+https://index.crates.io/",
    }
)
PYPI_INDEX: Final = frozenset({"https://pypi.org/simple", "https://pypi.org/simple/"})


class UvLockfile:
    """`uv.lock`: packages whose source is the PyPI registry."""

    @staticmethod
    def parse(text: str) -> tuple[LockedPackage, ...]:
        """The PyPI packages pinned by a uv lockfile."""
        return tuple(
            LockedPackage(EcosystemPackage.PYPI, package["name"], package["version"])
            for package in tomllib.loads(text).get("package", ())
            if package.get("source", {}).get("registry") in PYPI_INDEX
        )


class CargoLockfile:
    """`Cargo.lock`: packages whose source is the crates.io index."""

    @staticmethod
    def parse(text: str) -> tuple[LockedPackage, ...]:
        """The crates.io packages pinned by a Cargo lockfile."""
        return tuple(
            LockedPackage(EcosystemPackage.CRATES, package["name"], package["version"])
            for package in tomllib.loads(text).get("package", ())
            if package.get("source") in CRATES_INDEX
        )


PARSERS: Final[Mapping[str, Callable[[str], tuple[LockedPackage, ...]]]] = MappingProxyType(
    {
        "uv.lock": UvLockfile.parse,
        "Cargo.lock": CargoLockfile.parse,
    }
)


def parse_lockfile(path: str, text: str) -> tuple[LockedPackage, ...]:
    """Packages pinned by a lockfile, picked by its file name; an unknown name raises KeyError."""
    return PARSERS[PurePosixPath(path).name](text)
