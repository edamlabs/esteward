"""The outcome of a check, ranked by the action it calls for."""

from enum import StrEnum, auto


class Verdict(StrEnum):
    """Ladder of a finding: ok, watch (dashboard only), act (deterministic action), escalate (an issue)."""

    OK = auto()
    WATCH = auto()
    ACT = auto()
    ESCALATE = auto()

    @property
    def rank(self) -> int:
        """Position on the ladder; the declaration order is the severity order."""
        return tuple(Verdict).index(self)
