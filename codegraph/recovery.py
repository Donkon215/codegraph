"""codegraph.recovery — Error recovery framework.

Implements structured recovery strategies for each failure mode listed
in the README's Failure Modes & Recovery table.
(Task A-032)
"""

from __future__ import annotations

import functools
import traceback
from typing import Any, Callable, Optional, TypeVar

from codegraph.exceptions import (
    ASTParseError,
    CodegraphError,
    DeltaUncommittedError,
    ModuleImportError,
    TraceCrashError,
)
from codegraph.logging_config import get_logger

logger = get_logger("recovery")

F = TypeVar("F", bound=Callable[..., Any])


# ── Recovery strategies ────────────────────────────────────────────────


def recover_ast_parse(error: ASTParseError) -> None:
    """Log and skip an unparsable file; processing continues."""
    logger.warning(
        "Skipping file due to AST parse error: %s (%s)", error.file, error.reason
    )


def recover_module_import(error: ModuleImportError) -> None:
    """Log unresolved module; mark as layer 1 (external)."""
    logger.warning(
        "Cannot resolve module '%s' — treating as external (layer 1)", error.module
    )


def recover_trace_crash(error: TraceCrashError) -> None:
    """Log trace failure; fall back to static analysis."""
    logger.warning(
        "Trace crashed for %s — falling back to static analysis: %s",
        error.file,
        error.reason,
    )


def recover_delta_uncommitted(error: DeltaUncommittedError) -> None:
    """Log uncommitted-changes warning; caller should fall back to full build."""
    logger.warning("Uncommitted changes — falling back to full build")


# ── Recovery map ───────────────────────────────────────────────────────

_RECOVERY_MAP: dict[type, Callable[[CodegraphError], None]] = {
    ASTParseError: recover_ast_parse,  # type: ignore[dict-item]
    ModuleImportError: recover_module_import,  # type: ignore[dict-item]
    TraceCrashError: recover_trace_crash,  # type: ignore[dict-item]
    DeltaUncommittedError: recover_delta_uncommitted,  # type: ignore[dict-item]
}


def attempt_recovery(error: CodegraphError) -> bool:
    """Attempt recovery for *error*.

    Returns *True* if a recovery strategy was executed, *False* otherwise.
    """
    handler = _RECOVERY_MAP.get(type(error))
    if handler:
        handler(error)
        return True
    logger.error("No recovery strategy for %s: %s", type(error).__name__, error)
    return False


# ── Decorator ──────────────────────────────────────────────────────────


def recoverable(
    default: Any = None,
    exceptions: tuple[type[CodegraphError], ...] = (CodegraphError,),
) -> Callable[[F], F]:
    """Decorator that catches *exceptions* and runs recovery.

    If recovery succeeds the decorated function returns *default*.
    If no recovery strategy exists, the exception propagates.

    Usage::

        @recoverable(default=[])
        def extract_file(path):
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except exceptions as exc:
                if attempt_recovery(exc):
                    return default
                raise

        return wrapper  # type: ignore[return-value]

    return decorator
