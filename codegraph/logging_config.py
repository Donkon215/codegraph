"""codegraph.logging_config — Centralized logging configuration.

Provides named loggers per component with support for human-readable
and JSON output formats.  (Task A-006)
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Optional


class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "component": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class _HumanFormatter(logging.Formatter):
    """Human-readable log format: ``timestamp  LEVEL  component — message``."""

    FMT = "%(asctime)s  %(levelname)-7s  %(name)s — %(message)s"
    DATE_FMT = "%Y-%m-%d %H:%M:%S"

    def __init__(self) -> None:
        super().__init__(fmt=self.FMT, datefmt=self.DATE_FMT)


_ROOT_LOGGER_NAME = "codegraph"
_configured = False


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
    stream: Optional[object] = None,
) -> None:
    """Configure the *codegraph* logger hierarchy.

    Parameters
    ----------
    level:
        One of DEBUG, INFO, WARNING, ERROR.
    json_format:
        When *True*, emit JSON log records (for agent consumption).
    stream:
        Output stream; defaults to ``sys.stderr``.
    """
    global _configured
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to allow re-configuration
    root.handlers.clear()

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(_JsonFormatter() if json_format else _HumanFormatter())
    root.addHandler(handler)
    _configured = True


def get_logger(component: str) -> logging.Logger:
    """Return a child logger under the *codegraph* namespace.

    >>> logger = get_logger("extractor")
    >>> logger.name
    'codegraph.extractor'
    """
    if not _configured:
        configure_logging()
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{component}")
