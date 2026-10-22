"""URL helpers: the parts of a repository or registry page URL the modules address things by."""

from urllib.parse import urlsplit


def slug_url(url: str) -> str:
    """`owner/name` of a repository URL: `https://github.com/edamlabs/esteward` → `edamlabs/esteward`."""
    return "/".join(urlsplit(url).path.strip("/").split("/")[:2])


def host_url(url: str) -> str:
    """Host of a URL, without `www.`: `https://www.pypi.org/project/x/` → `pypi.org`."""
    return urlsplit(url).netloc.removeprefix("www.")


def name_url(url: str) -> str:
    """Last path segment of a registry page: `https://pypi.org/project/lxml/` → `lxml`."""
    return urlsplit(url).path.strip("/").rsplit("/", 1)[-1]
