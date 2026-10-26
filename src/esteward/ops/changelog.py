"""Keep-a-Changelog documents: the unreleased section, the latest version, and the release fold."""

import re
from typing import Final

from esteward.ops.semver import Semver

UNRELEASED: Final = "## [Unreleased]"
HEADING: Final = re.compile(r"^## \[([^\]]+)\]")
SUBSECTION: Final = "###"
EM: Final = "—"


class Changelog:
    """One Keep-a-Changelog document, held by its lines."""

    __slots__ = ("_lines",)

    def __init__(self, text: str) -> None:
        self._lines = text.splitlines()

    ##### PRIVATE #####

    def _common_span(self) -> tuple[int, int] | None:
        """The `(start, end)` line indexes of the Unreleased section; None when the document has none."""
        match next((index for index, line in enumerate(self._lines) if line.strip() == UNRELEASED), None):
            case None:
                return None
            case start:
                end = next(
                    (index for index in range(start + 1, len(self._lines)) if HEADING.match(self._lines[index])),
                    len(self._lines),
                )
                return start, end

    ############################################################

    ##### PUBLIC #####

    def unreleased(self) -> tuple[str, ...]:
        """The content lines of the Unreleased section, blanks dropped; empty when there is none."""
        match self._common_span():
            case None:
                return ()
            case span:
                start, end = span
                return tuple(line for line in self._lines[start + 1 : end] if line.strip())

    def sections(self) -> frozenset[str]:
        """The `###` subsection names of the Unreleased section: Added, Fixed, Security…"""
        return frozenset(
            line.removeprefix(SUBSECTION).strip() for line in self.unreleased() if line.startswith(SUBSECTION)
        )

    def latest(self) -> str | None:
        """The highest version the document's headings name; None when it names no version."""
        return Semver.latest(
            tuple(found[1] for line in self._lines if (found := HEADING.match(line)) and found[1] != "Unreleased")
        )

    def fold(self, version: str, date: str, subjects: tuple[str, ...]) -> str:
        """The document with one release folded in, line for line the fold of e-serde's release workflow.

        `[Unreleased]`'s curated notes become the body; when the section is empty, the commit subjects do.
        """
        match self._common_span():
            case None:
                message = f"cannot fold v{version}: the changelog has no {UNRELEASED} heading"
                raise ValueError(message)
            case span:
                start, end = span
                inside = self._lines[start + 1 : end]
                body = (
                    list(inside)
                    if any(line.strip() for line in inside)
                    else [*inside, *(f"- {subject}" for subject in subjects), ""]
                )
                return (
                    "\n".join(
                        [
                            *self._lines[: start + 1],
                            "",
                            f"## [{version}] {EM} {date}",
                            *body,
                            *self._lines[end:],
                        ]
                    )
                    + "\n"
                )
