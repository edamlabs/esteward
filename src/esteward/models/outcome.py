"""What a tool run in the workspace returned."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """One finished subprocess: its return code and its captured streams."""

    rc: int
    out: str
    err: str
