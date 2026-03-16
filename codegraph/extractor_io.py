"""codegraph.extractor_io — Graph_0 persistence I/O.

Separated from extraction logic to keep extractor responsibilities focused.
"""

from __future__ import annotations

import json
from pathlib import Path

from codegraph.constants import GRAPHS_DIR
from codegraph.logging_config import get_logger
from codegraph.models.graph0 import Graph0
from codegraph.storage import ensure_codegraph_dir, resolve_path

logger = get_logger("extractor_io")


def save_graph0(graph0: Graph0, project_root: Path) -> Path:
    """Persist *graph0* to ``.codegraph/graphs/graph0.json``."""
    from codegraph.storage import atomic_write

    ensure_codegraph_dir(project_root)
    dest = resolve_path(project_root, GRAPHS_DIR, "graph0.json")
    data = json.loads(graph0.to_json())
    atomic_write(dest, data)
    logger.info("Saved Graph_0 (%d nodes) → %s", len(graph0.nodes), dest)
    return dest


def load_graph0(project_root: Path) -> Graph0:
    """Load Graph_0 from ``.codegraph/graphs/graph0.json``.

    Returns an empty Graph0 if the file does not exist.
    """
    path = resolve_path(project_root, GRAPHS_DIR, "graph0.json")
    if not path.exists():
        logger.debug("No graph0.json found — returning empty Graph_0")
        return Graph0()

    try:
        text = path.read_text(encoding="utf-8")
        return Graph0.from_json(text)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.error("Corrupted graph0.json: %s", exc)
        raise ValueError(f"Corrupted graph0.json: {exc}") from exc
