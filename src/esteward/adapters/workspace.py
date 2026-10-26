"""The workspace: one managed git checkout per repository, where cargo and uv run."""

import asyncio
import os
import shutil
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Final

from esteward.models.outcome import RunOutcome

### Commits speak for the engine, never for the token holder that happens to run it.
IDENTITY: Final = (("user.name", "esteward[bot]"), ("user.email", "eself-maintenance[bot]@users.noreply.github.com"))
CREDENTIAL: Final = "x-access-token"
HTTP: Final = ("http://", "https://")


class WorkspaceAdapter:
    """Git shelled out: a fresh shallow clone per checkout, tools run inside it, pushes carry the token.

    The remote is a template with one `{slug}` placeholder. A token is injected as the HTTP password of an
    http(s) remote; any other scheme keeps its URL untouched. Every subprocess is bounded by one timeout; a
    timeout kills the process and raises, because it is an infrastructure fault, never a verdict.
    """

    __slots__ = ("_directory", "_remote", "_timeout", "_token", "_work")

    def __init__(self, work_dir: Path, remote: str, token: str | None, timeout: timedelta) -> None:
        self._work = work_dir
        self._remote = remote
        self._token = token
        self._timeout = timeout.total_seconds()
        self._directory: Path | None = None

    ##### PRIVATE #####

    def _common_directory(self, slug: str) -> Path:
        return self._work / slug.replace("/", "-")

    def _common_remote(self, slug: str) -> str:
        """The clone URL of a slug, authenticated when a token is set and the remote is HTTP."""
        url = self._remote.format(slug=slug)
        match self._token:
            case None:
                return url
            case token if url.startswith(HTTP):
                scheme, rest = url.split("://", 1)
                return f"{scheme}://{CREDENTIAL}:{token}@{rest}"
            case _:
                return url

    def _common_checked(self) -> Path:
        """The checkout directory; using the workspace before checkout is a bug."""
        match self._directory:
            case None:
                message = "the workspace is not checked out"
                raise RuntimeError(message)
            case directory:
                return directory

    async def _common_exec(self, argv: tuple[str, ...], directory: Path) -> RunOutcome:
        """One subprocess inside a directory, bounded by the timeout; a timeout kills it and raises."""
        process = await asyncio.create_subprocess_exec(
            *argv,
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=os.environ | {"GIT_TERMINAL_PROMPT": "0"},
        )
        try:
            out, err = await asyncio.wait_for(process.communicate(), self._timeout)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            message = f"{' '.join(argv[:2])} timed out after {self._timeout} s"
            raise TimeoutError(message) from exc
        return RunOutcome(process.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace"))

    async def _common_git(self, argv: tuple[str, ...], directory: Path) -> RunOutcome:
        """One git run that must succeed; anything but zero raises with git's own words."""
        outcome = await self._common_exec(("git", *argv), directory)
        match outcome.rc:
            case 0:
                return outcome
            case _:
                message = f"git {argv[0]} failed: {outcome.err.strip() or outcome.out.strip()}"
                raise RuntimeError(message)

    ############################################################

    ##### PUBLIC #####

    async def checkout(self, slug: str) -> None:
        """A fresh shallow clone of a repository, replacing any previous workspace of the same slug."""
        directory = self._common_directory(slug)
        shutil.rmtree(directory, ignore_errors=True)
        directory.parent.mkdir(parents=True, exist_ok=True)
        outcome = await self._common_exec(
            ("git", "clone", "--quiet", "--depth", "1", self._common_remote(slug), directory.name), directory.parent
        )
        match outcome.rc:
            case 0:
                self._directory = directory
            case _:
                message = f"clone of {slug} failed: {outcome.err.strip() or outcome.out.strip()}"
                raise RuntimeError(message)

    async def run(self, argv: tuple[str, ...]) -> RunOutcome:
        """One tool run inside the checkout; a failing tool is data, never an error."""
        return await self._common_exec(argv, self._common_checked())

    async def read(self, path: str) -> str | None:
        """One file of the checkout as text; None when absent."""
        file = self._common_checked() / PurePosixPath(path)
        return file.read_text(encoding="utf-8") if file.is_file() else None

    async def commit(self, branch: str, message: str) -> bool:
        """Branch from the current base, stage everything, commit; whether the checkout had changed."""
        directory = self._common_checked()
        await self._common_git(("checkout", "--quiet", "-B", branch), directory)
        await self._common_git(("add", "-A"), directory)
        status = await self._common_git(("status", "--porcelain"), directory)
        match status.out.strip():
            case "":
                return False
            case _:
                identity = tuple(flag for pair in IDENTITY for flag in ("-c", f"{pair[0]}={pair[1]}"))
                await self._common_git((*identity, "commit", "--quiet", "-m", message), directory)
                return True

    async def push(self, branch: str) -> None:
        """Force one branch to the remote: a re-run of the same act converges on its branch, never forks it."""
        await self._common_git(("push", "--quiet", "--force", "origin", branch), self._common_checked())

    async def restore(self) -> None:
        """Back to a pristine base: detached at origin/HEAD, tracked edits and untracked leftovers gone."""
        directory = self._common_checked()
        await self._common_git(("checkout", "--quiet", "--force", "--detach", "origin/HEAD"), directory)
        await self._common_git(("clean", "-fdq"), directory)
