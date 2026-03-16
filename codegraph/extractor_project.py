from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from codegraph.config import CodegraphConfig
from codegraph.models.graph0 import Graph0


def extract_project_graph(
    project_root: Path,
    config: Optional[CodegraphConfig] = None,
) -> Tuple[Graph0, object]:
    from codegraph.extractor import extract_project

    return extract_project(project_root, config)
