"""codegraph.utils.json_cache — Mtime-gated in-process JSON file cache.

Avoids redundant disk reads when multiple commands (focus, hotspots, scope,
copilot-loop) load the same graph JSON files in the same process invocation.

The cache is process-scoped and invalidated automatically when the file's
mtime changes, so callers always see fresh data after a ``codegraph build``.

Usage::

    from codegraph.utils.json_cache import load_json_cached, clear_json_cache

    data = load_json_cached(path)          # dict | list
    load_json_cached.cache_clear()         # or clear_json_cache()
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

# {absolute_path_str: (mtime_float, parsed_data)}
_CACHE: Dict[str, Tuple[float, Any]] = {}


def load_json_cached(path: Path, default: Any = None) -> Any:
    """Return parsed JSON from *path*, re-reading only when mtime changes.

    Args:
        path: File to read.
        default: Value to return when the file does not exist or is unreadable.
                 Defaults to ``None``; pass ``{}`` or ``[]`` as needed.

    Returns:
        Parsed JSON value (dict, list, etc.) or *default*.
    """
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return default if default is not None else {}

    entry = _CACHE.get(key)
    if entry is not None and entry[0] == mtime:
        return entry[1]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}

    _CACHE[key] = (mtime, data)
    return data


def clear_json_cache() -> None:
    """Evict all cached entries (useful in tests or after a build step)."""
    _CACHE.clear()
