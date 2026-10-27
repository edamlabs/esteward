"""GitHub REST: the code host (repositories, files, commits) and the tracker (issues) of the fleet."""

import asyncio
from datetime import datetime
from http import HTTPStatus
from typing import Any, Final, assert_never
from urllib.parse import quote

import wreq

from esteward.models.issue import (
    CloseIssue,
    CommentIssue,
    CreateIssue,
    Issue,
    LabelIssue,
    OperationIssue,
    PinIssue,
    UpdateIssue,
)
from esteward.models.pull import AutomergePull, CreatePull, OperationPull, Pull, TriagePull, UpdatePull
from esteward.models.signal import CommitSignal, RepositorySignal

API_VERSION: Final = "2022-11-28"
JSON: Final = "application/vnd.github+json"
RAW: Final = "application/vnd.github.raw+json"
ABSENT: Final = frozenset({HTTPStatus.NOT_FOUND, HTTPStatus.UNPROCESSABLE_ENTITY})
### A merged act PR is a squash: the branch is esteward's, its one commit is the whole change.
AUTOMERGE: Final = (
    "mutation($node: ID!) {"
    " enablePullRequestAutoMerge(input: {pullRequestId: $node, mergeMethod: SQUASH}) { clientMutationId }"
    " }"
)
### Pinning lives only in GraphQL; a repository holds at most three pinned issues.
PINNED: Final = (
    "query($owner: String!, $name: String!, $number: Int!) {"
    " repository(owner: $owner, name: $name) {"
    " issue(number: $number) { id }"
    " pinnedIssues(first: 3) { nodes { issue { number } } }"
    " } }"
)
PIN: Final = "mutation($id: ID!) { pinIssue(input: {issueId: $id}) { issue { number } } }"
### A renamed or transferred repository answers 301/307 with its new API location; followed once.
MOVED: Final = frozenset(
    {HTTPStatus.MOVED_PERMANENTLY, HTTPStatus.FOUND, HTTPStatus.TEMPORARY_REDIRECT, HTTPStatus.PERMANENT_REDIRECT}
)
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
        return await self._common_fetch(f"{self._api}{path}", accept, follow=True)

    async def _common_fetch(self, url: str, accept: str, *, follow: bool) -> wreq.Response | None:
        """GET a URL, following one redirect of a moved repository; None on absence, any other error raised."""
        response = await self._client.get(url, headers=self._headers | {"Accept": accept})
        match response.status.as_int(), response.headers.get("location"):
            case status, _ if status in ABSENT:
                return None
            case status, location if status in MOVED and follow and location is not None:
                return await self._common_fetch(bytes(location).decode(), accept, follow=False)
            case status, _ if status in MOVED:
                message = f"GitHub redirected twice from {url}: a moved repository is followed once"
                raise ValueError(message)
            case _:
                response.raise_for_status()
                return response

    async def _common_send(self, method: wreq.Method, path: str, payload: dict[str, Any]) -> wreq.Response:
        """A write to the API; any non-2xx raises."""
        response = await self._client.request(
            method, f"{self._api}{path}", headers=self._headers | {"Accept": JSON}, json=payload
        )
        response.raise_for_status()
        return response

    async def _common_graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """One GraphQL call; GitHub answers errors in a 200, so the errors array is the failure."""
        response = await self._client.post(
            f"{self._api}/graphql", headers=self._headers, json={"query": query, "variables": variables}
        )
        response.raise_for_status()
        payload = await response.json()
        match payload.get("errors"):
            case None:
                return payload["data"]
            case errors:
                message = f"GitHub GraphQL: {errors[0]['message']}"
                raise ValueError(message)

    @staticmethod
    def _common_moment(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    @staticmethod
    def _pull_build(item: dict[str, Any]) -> Pull:
        return Pull(
            number=item["number"],
            node=item["node_id"],
            branch=item["head"]["ref"],
            body=item.get("body") or "",
            automerge=item.get("auto_merge") is not None,
            url=item["html_url"],
            merge_sha=item.get("merge_commit_sha"),
        )

    async def _apply_automerge(self, node: str) -> None:
        """Squash auto-merge on one pull request: it merges itself when every required check passes."""
        await self._common_graphql(AUTOMERGE, {"node": node})

    async def _apply_base(self, slug: str) -> str:
        """The base of a new pull request: REST demands it, and the default branch is the only honest answer."""
        match await self._common_get(f"/repos/{slug}"):
            case None:
                message = f"cannot open a pull request: repository {slug} not found"
                raise ValueError(message)
            case response:
                return (await response.json())["default_branch"]

    async def _apply_pin(self, slug: str, number: int) -> None:
        """Pin one issue, unless it already is: the pinned state lives only in GraphQL."""
        owner, name = slug.split("/", 1)
        data = await self._common_graphql(PINNED, {"owner": owner, "name": name, "number": number})
        match data["repository"]["issue"]:
            case None:
                message = f"cannot pin: issue {slug}#{number} not found"
                raise ValueError(message)
            case issue:
                pinned = frozenset(node["issue"]["number"] for node in data["repository"]["pinnedIssues"]["nodes"])
                match number in pinned:
                    case True:
                        return
                    case _:
                        await self._common_graphql(PIN, {"id": issue["id"]})

    ############################################################

    ##### PUBLIC #####

    async def repository(self, slug: str) -> RepositorySignal | None:
        """Archived flag and last push of a repository; None when it does not exist."""
        match await self._common_get(f"/repos/{slug}"):
            case None:
                return None
            case response:
                data = await response.json()
                moved = data["full_name"] if data["full_name"].lower() != slug.lower() else None
                return RepositorySignal(slug, bool(data["archived"]), self._common_moment(data.get("pushed_at")), moved)

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

    async def tags(self, slug: str) -> tuple[str, ...]:
        """Every `v*` tag of a repository; empty for an unknown repository."""
        match await self._common_get(f"/repos/{slug}/git/matching-refs/tags/v?per_page=100"):
            case None:
                return ()
            case response:
                return tuple(ref["ref"].removeprefix("refs/tags/") for ref in await response.json())

    async def commits(self, slug: str, since: str) -> tuple[CommitSignal, ...]:
        """The commits between a reference and HEAD, oldest first; empty when the reference is HEAD."""
        match await self._common_get(f"/repos/{slug}/compare/{quote(since, safe='')}...HEAD"):
            case None:
                return ()
            case response:
                return tuple(
                    CommitSignal(
                        item["commit"]["message"].split("\n", 1)[0],
                        datetime.fromisoformat(item["commit"]["committer"]["date"]),
                    )
                    for item in (await response.json()).get("commits", ())
                )

    async def _issues_page(self, slug: str, label: str) -> tuple[Issue, ...]:
        """One read of the open issues carrying a label, pull requests excluded."""
        match await self._common_get(f"/repos/{slug}/issues?labels={quote(label)}&state=open&per_page=100"):
            case None:
                return ()
            case response:
                return tuple(self._issue_build(item) for item in await response.json() if "pull_request" not in item)

    @staticmethod
    def _issue_build(item: dict[str, Any]) -> Issue:
        return Issue(
            number=item["number"],
            title=item["title"],
            body=item.get("body") or "",
            author=item["user"]["login"],
            association=item["author_association"],
            labels=tuple(label["name"] for label in item["labels"]),
            updated=datetime.fromisoformat(item["updated_at"]),
        )

    @staticmethod
    def _triage_build(item: dict[str, Any]) -> TriagePull:
        return TriagePull(
            number=item["number"],
            author=item["user"]["login"],
            association=item["author_association"],
            labels=tuple(label["name"] for label in item["labels"]),
            updated=datetime.fromisoformat(item["updated_at"]),
            draft=bool(item["draft"]),
        )

    async def open_issues(self, slug: str) -> tuple[Issue, ...]:
        """Every open issue of a repository, pull requests excluded."""
        match await self._common_get(f"/repos/{slug}/issues?state=open&per_page=100"):
            case None:
                return ()
            case response:
                return tuple(self._issue_build(item) for item in await response.json() if "pull_request" not in item)

    async def open_pulls(self, slug: str) -> tuple[TriagePull, ...]:
        """Every open pull request of a repository, drafts included."""
        match await self._common_get(f"/repos/{slug}/pulls?state=open&per_page=100"):
            case None:
                return ()
            case response:
                return tuple(self._triage_build(item) for item in await response.json())

    async def issues(self, slug: str, label: str) -> tuple[Issue, ...]:
        """Open issues carrying a label, by number: the union of LISTING_READS reads, never one empty answer."""
        pages = [await self._issues_page(slug, label) for _ in range(LISTING_READS)]
        return tuple(sorted({issue.number: issue for page in pages for issue in page}.values(), key=lambda i: i.number))

    async def pull(self, slug: str, branch: str) -> Pull | None:
        """The open pull request of one head branch; None when the branch has no open pull request."""
        owner = slug.split("/", 1)[0]
        match await self._common_get(f"/repos/{slug}/pulls?state=open&head={quote(f'{owner}:{branch}', safe=':/')}"):
            case None:
                return None
            case response:
                return next((self._pull_build(item) for item in await response.json()), None)

    async def merged(self, slug: str, branch: str) -> Pull | None:
        """The merged pull request of one head branch, its merge commit included; None when it never merged."""
        owner = slug.split("/", 1)[0]
        match await self._common_get(f"/repos/{slug}/pulls?state=closed&head={quote(f'{owner}:{branch}', safe=':/')}"):
            case None:
                return None
            case response:
                return next((self._pull_build(item) for item in await response.json() if item.get("merged_at")), None)

    async def apply(self, slug: str, operation: OperationIssue | OperationPull) -> None:
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
            case PinIssue(number=number):
                await self._apply_pin(slug, number)
            case LabelIssue(number=number, add=add, remove=remove):
                match add:
                    case ():
                        pass
                    case labels:
                        await self._common_send(
                            wreq.Method.POST, f"/repos/{slug}/issues/{number}/labels", {"labels": list(labels)}
                        )
                await asyncio.gather(
                    *(
                        self._common_send(wreq.Method.DELETE, f"/repos/{slug}/issues/{number}/labels/{quote(name)}", {})
                        for name in remove
                    )
                )
            case CommentIssue(number=number, body=body):
                await self._common_send(wreq.Method.POST, f"/repos/{slug}/issues/{number}/comments", {"body": body})
            case CreatePull(branch=branch, title=title, body=body):
                response = await self._common_send(
                    wreq.Method.POST,
                    f"/repos/{slug}/pulls",
                    {"title": title, "head": branch, "base": await self._apply_base(slug), "body": body},
                )
                await self._apply_automerge((await response.json())["node_id"])
            case UpdatePull(number=number, body=body):
                await self._common_send(wreq.Method.PATCH, f"/repos/{slug}/pulls/{number}", {"body": body})
            case AutomergePull(node=node):
                await self._apply_automerge(node)
            case unreachable:
                assert_never(unreachable)
