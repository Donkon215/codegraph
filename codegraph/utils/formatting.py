"""codegraph.utils.formatting — Timestamps and JSON formatting.

(Tasks A-024, A-034)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


# ── A-024  Timestamps ─────────────────────────────────────────────────


def iso_now() -> str:
    """Return the current UTC time as ISO 8601 string ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 timestamp to a timezone-aware :class:`datetime`."""
    s = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s)


# ── A-034  JSON pretty-printer ────────────────────────────────────────


def format_json(data: Any, compact: bool = False) -> str:
    """Serialize *data* as a JSON string.

    Parameters
    ----------
    data:
        Any JSON-serializable object.
    compact:
        If *True*, use single-line output (for piping to agents).
    """
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, indent=2, ensure_ascii=False)
