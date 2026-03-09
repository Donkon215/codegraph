"""codegraph.known_libraries — Known library database for semantic extraction.

Task R-015 supplement — provides structured library metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from codegraph.models.graph2 import SideEffectType


@dataclass(frozen=True)
class LibraryInfo:
    """Metadata about a known library."""

    name: str
    category: str  # e.g. "http", "database", "testing", "io"
    side_effects: List[SideEffectType] = field(default_factory=list)
    domain_tags: List[str] = field(default_factory=list)

    def __hash__(self) -> int:
        return hash(self.name)


# ═══════════════════════════════════════════════════════════════════════
# Library Registry
# ═══════════════════════════════════════════════════════════════════════

_LIBRARY_DB: Dict[str, LibraryInfo] = {
    # HTTP / Network
    "requests": LibraryInfo("requests", "http", [SideEffectType.NETWORK_CALL], ["network"]),
    "httpx": LibraryInfo("httpx", "http", [SideEffectType.NETWORK_CALL], ["network"]),
    "aiohttp": LibraryInfo("aiohttp", "http", [SideEffectType.NETWORK_CALL], ["network"]),
    "urllib": LibraryInfo("urllib", "http", [SideEffectType.NETWORK_CALL], ["network"]),
    "urllib3": LibraryInfo("urllib3", "http", [SideEffectType.NETWORK_CALL], ["network"]),

    # Database
    "sqlite3": LibraryInfo("sqlite3", "database", [SideEffectType.DATABASE_READ, SideEffectType.DATABASE_WRITE], ["database"]),
    "psycopg2": LibraryInfo("psycopg2", "database", [SideEffectType.DATABASE_READ, SideEffectType.DATABASE_WRITE], ["database"]),
    "pymongo": LibraryInfo("pymongo", "database", [SideEffectType.DATABASE_READ, SideEffectType.DATABASE_WRITE], ["database"]),
    "sqlalchemy": LibraryInfo("sqlalchemy", "database", [SideEffectType.DATABASE_READ, SideEffectType.DATABASE_WRITE], ["database"]),
    "redis": LibraryInfo("redis", "cache", [SideEffectType.CACHE_READ, SideEffectType.CACHE_WRITE], ["cache", "database"]),

    # Web Frameworks
    "flask": LibraryInfo("flask", "web", [SideEffectType.NETWORK_CALL], ["api"]),
    "django": LibraryInfo("django", "web", [SideEffectType.NETWORK_CALL, SideEffectType.DATABASE_WRITE], ["api", "database"]),
    "fastapi": LibraryInfo("fastapi", "web", [SideEffectType.NETWORK_CALL], ["api"]),
    "starlette": LibraryInfo("starlette", "web", [SideEffectType.NETWORK_CALL], ["api"]),

    # File I/O
    "pathlib": LibraryInfo("pathlib", "io", [SideEffectType.FILE_READ, SideEffectType.FILE_WRITE], ["io"]),
    "shutil": LibraryInfo("shutil", "io", [SideEffectType.FILE_WRITE], ["io"]),
    "tempfile": LibraryInfo("tempfile", "io", [SideEffectType.FILE_WRITE], ["io"]),
    "io": LibraryInfo("io", "io", [SideEffectType.FILE_READ, SideEffectType.FILE_WRITE], ["io"]),

    # Process / System
    "subprocess": LibraryInfo("subprocess", "system", [SideEffectType.PROCESS_SPAWN], ["io"]),
    "os": LibraryInfo("os", "system", [SideEffectType.SYSTEM_CALL], ["io"]),
    "sys": LibraryInfo("sys", "system", [], []),

    # Logging
    "logging": LibraryInfo("logging", "logging", [SideEffectType.LOGGING], ["logging"]),

    # Serialization
    "json": LibraryInfo("json", "serialization", [], ["serialization"]),
    "yaml": LibraryInfo("yaml", "serialization", [], ["serialization"]),
    "toml": LibraryInfo("toml", "serialization", [], ["serialization"]),
    "csv": LibraryInfo("csv", "serialization", [SideEffectType.FILE_READ], ["serialization"]),
    "xml": LibraryInfo("xml", "serialization", [], ["serialization"]),
    "pickle": LibraryInfo("pickle", "serialization", [SideEffectType.FILE_READ, SideEffectType.FILE_WRITE], ["serialization", "security"]),

    # Security / Crypto
    "hashlib": LibraryInfo("hashlib", "crypto", [], ["security"]),
    "hmac": LibraryInfo("hmac", "crypto", [], ["security"]),
    "secrets": LibraryInfo("secrets", "crypto", [], ["security"]),
    "cryptography": LibraryInfo("cryptography", "crypto", [], ["security"]),
    "jwt": LibraryInfo("jwt", "auth", [], ["auth", "security"]),

    # Testing
    "pytest": LibraryInfo("pytest", "testing", [], ["testing"]),
    "unittest": LibraryInfo("unittest", "testing", [], ["testing"]),
    "mock": LibraryInfo("mock", "testing", [], ["testing"]),
    "hypothesis": LibraryInfo("hypothesis", "testing", [], ["testing"]),

    # Data / Science
    "numpy": LibraryInfo("numpy", "data", [], []),
    "pandas": LibraryInfo("pandas", "data", [SideEffectType.FILE_READ], []),
    "scipy": LibraryInfo("scipy", "data", [], []),

    # CLI
    "click": LibraryInfo("click", "cli", [], ["config"]),
    "typer": LibraryInfo("typer", "cli", [], ["config"]),
    "argparse": LibraryInfo("argparse", "cli", [], ["config"]),

    # Messaging
    "celery": LibraryInfo("celery", "messaging", [SideEffectType.MESSAGE_PUBLISH], ["messaging", "scheduling"]),
    "kombu": LibraryInfo("kombu", "messaging", [SideEffectType.MESSAGE_PUBLISH, SideEffectType.MESSAGE_CONSUME], ["messaging"]),

    # Cloud
    "boto3": LibraryInfo("boto3", "cloud", [SideEffectType.NETWORK_CALL], ["network"]),
    "botocore": LibraryInfo("botocore", "cloud", [SideEffectType.NETWORK_CALL], ["network"]),

    # Templating
    "jinja2": LibraryInfo("jinja2", "templating", [], ["ui"]),
    "mako": LibraryInfo("mako", "templating", [], ["ui"]),

    # Validation
    "pydantic": LibraryInfo("pydantic", "validation", [], ["validation"]),
    "marshmallow": LibraryInfo("marshmallow", "validation", [], ["validation"]),
    "attrs": LibraryInfo("attrs", "validation", [], ["validation"]),
}


def get_library_info(name: str) -> Optional[LibraryInfo]:
    """Look up metadata for a known library."""
    return _LIBRARY_DB.get(name)


def get_all_known_names() -> Set[str]:
    """Return set of all known library names."""
    return set(_LIBRARY_DB.keys())


def get_libraries_by_category(category: str) -> List[LibraryInfo]:
    """Return all libraries in a given category."""
    return [lib for lib in _LIBRARY_DB.values() if lib.category == category]


def enrich_side_effects_from_library(
    library_name: str,
) -> List[SideEffectType]:
    """Get side effect types that a library typically produces."""
    info = _LIBRARY_DB.get(library_name)
    return list(info.side_effects) if info else []


def enrich_domain_tags_from_library(
    library_name: str,
) -> List[str]:
    """Get domain tags associated with a library."""
    info = _LIBRARY_DB.get(library_name)
    return list(info.domain_tags) if info else []
