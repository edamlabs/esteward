"""Structured logging: one `setup()` at the composition root, `structlog.get_logger()` everywhere else."""

import logging
import sys
from types import MappingProxyType
from typing import Final

import structlog

from esteward.core.settings import EnvSettings

RENDERERS: Final = MappingProxyType(
    {
        EnvSettings.DEV: structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        EnvSettings.PROD: structlog.processors.JSONRenderer(),
    }
)


def setup_logger(env: EnvSettings, level: str) -> None:
    """Configure structlog once: events on stderr, flat in DEV, JSON in PROD, filtered below `level`."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            RENDERERS[env],
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level.upper()]),
        logger_factory=lambda *_: structlog.PrintLogger(sys.stderr),
        ### A CLI emits tens of events: binding stderr per call keeps redirection and capture honest.
        cache_logger_on_first_use=False,
    )
