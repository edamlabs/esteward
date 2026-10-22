"""Session fixtures: the fixed clock and the resource tree."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import structlog

RESOURCES = Path(__file__).parent / "resources"


@pytest.fixture(scope="session")
def resources() -> Path:
    """Root of the physical fixture files."""
    return RESOURCES


@pytest.fixture(scope="session")
def now() -> datetime:
    """The fixed moment every run in the suite observes."""
    return datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def pristine_logging() -> Iterator[None]:
    """No test inherits another's structlog configuration."""
    yield
    structlog.reset_defaults()
