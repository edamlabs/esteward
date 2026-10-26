"""Agnostic URL operations: one parse, every part the callers address things by."""

from urllib.parse import urlsplit


class Url:
    """One URL parsed once: the repository slug, the registry host, the package name."""

    __slots__ = ("_parts",)

    def __init__(self, url: str) -> None:
        self._parts = urlsplit(url)

    ##### PRIVATE #####

    def _common_segments(self) -> list[str]:
        """The path segments: what slug and name both cut from."""
        return self._parts.path.strip("/").split("/")

    ############################################################

    ##### PUBLIC #####

    def slug(self) -> str:
        """`owner/name` of a repository URL: `https://github.com/edamlabs/esteward` → `edamlabs/esteward`."""
        return "/".join(self._common_segments()[:2])

    def host(self) -> str:
        """The host without `www.`: `https://www.pypi.org/project/x/` → `pypi.org`."""
        return self._parts.netloc.removeprefix("www.")

    def name(self) -> str:
        """The last path segment of a registry page: `https://pypi.org/project/lxml/` → `lxml`."""
        return self._common_segments()[-1]
