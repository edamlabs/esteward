"""GitHub REST: the code host (repositories, files, commits) and the tracker (issues) of the fleet."""

from datetime import datetime
from http import HTTPStatus
from typing import Any, Final, assert_never
from urllib.parse import quote

import wreq

from esteward.models.issue import CloseIssue, CreateIssue, Issue, OperationIssue, UpdateIssue
from esteward.models.signal import RepositorySignal

API_VERSION: Final = "2022-11-28"
JSON: Final = "application/vnd.github+json"
RAW: Final = "application/vnd.github.raw+json"
ABSENT: Final = frozenset({HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY})
### GitHub intermittently answers an issue listing with an empty 200 (measured: 2 in 16 reads); reads are united.
LISTING_READS: Final = 3


class GithubAdapter:
    """One GitHub API client: authenticated when a token is given, 404 read as absence, any other error raised."""

    __slots__ = ("_api", "_client", "_headers")

    def __init__(self, client: wreq.Client, api: str, token: str | None, user_agent: str) -> None:
        self._client = client
        self._api = api.rstrip("/")
        self._headers = {"X-GitHub-Api-Version": API_VERSION, "User-Agent": user_agent} | (
            {"Authorization": f"Bearer {token}"} if token else {}
        )

    ##### PRIVATE #####

    async def _common_get(self, path: str, accept: str = JSON) -> wreq.Response | None:
        """GET an API path; None when the resource does not exist."""
        response = await self._client.get(f"{self._api}{path}", headers=self._headers | {"Accept": accept})
        match response.status.as_int():
            case status if status in ABSENT:
                return None
            case _:
                response.raise_for_status()
                return response

    async def _common_send(self, method: wreq.Method, path: str, payload: dict[str, Any]) -> None:
        """A write to the API; any non-2xx raises."""
        response = await self._client.request(
            method, f"{self._api}{path}", headers=self._headers | {"Accept": JSON}, json=payload
        )
        response.raise_for_status()

    @staticmethod
    def _common_moment(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    ############################################################

    ##### PUBLIC #####

    async def repository(self, slug: str) -> RepositorySignal | None:
        """Archived flag and last push of a repository; None when it does not exist."""
        match await self._common_get(f"/repos/{slug}"):
            case None:
                return None
            case response:
                data = await response.json()
                return RepositorySignal(slug, bool(data["archived"]), self._common_moment(data.get("pushed_at")))

    async def file(self, slug: str, path: str) -> str | None:
        """Raw content of a file on the default branch; None when absent."""
        match await self._common_get(f"/repos/{slug}/contents/{quote(path)}", RAW):
            case None:
                return None
            case response:
                return await response.text()

    async def tree(self, slug: str) -> tuple[str, ...]:
        """Every file path of the default branch, in one recursive git-tree call; empty for an unknown repository."""
        match await self._common_get(f"/repos/{slug}/git/trees/HEAD?recursive=1"):
            case None:
                return ()
            case response:
                return tuple(entry["path"] for entry in (await response.json())["tree"] if entry["type"] == "blob")

    async def commit(self, slug: str, sha: str) -> bool:
        """Whether a commit exists in a repository."""
        return await self._common_get(f"/repos/{slug}/commits/{sha}") is not None

    async def _issues_page(self, slug: str, label: str) -> tuple[Issue, ...]:
        """One read of the open issues carrying a label, pull requests excluded."""
        match await self._common_get(f"/repos/{slug}/issues?labels={quote(label)}&state=open&per_page=100"):
            case None:
                return ()
            case response:
                return tuple(
                    Issue(item["number"], item["title"], item.get("body") or "")
                    for item in await response.json()
                    if "pull_request" not in item
                )

    async def issues(self, slug: str, label: str) -> tuple[Issue, ...]:
        """Open issues carrying a label, by number: the union of LISTING_READS reads, never one empty answer."""
        pages = [await self._issues_page(slug, label) for _ in range(LISTING_READS)]
        return tuple(sorted({issue.number: issue for page in pages for issue in page}.values(), key=lambda i: i.number))

    async def apply(self, slug: str, operation: OperationIssue) -> None:
        """Carry out one planned tracker operation."""
        match operation:
            case CreateIssue(title=title, body=body, labels=labels):
                await self._common_send(
                    wreq.Method.POST, f"/repos/{slug}/issues", {"title": title, "body": body, "labels": list(labels)}
                )
            case UpdateIssue(number=number, title=title, body=body):
                await self._common_send(
                    wreq.Method.PATCH, f"/repos/{slug}/issues/{number}", {"title": title, "body": body}
                )
            case CloseIssue(number=number, comment=comment):
                await self._common_send(wreq.Method.POST, f"/repos/{slug}/issues/{number}/comments", {"body": comment})
                await self._common_send(
                    wreq.Method.PATCH,
                    f"/repos/{slug}/issues/{number}",
                    {"state": "closed", "state_reason": "completed"},
                )
            case unreachable:
                assert_never(unreachable)
