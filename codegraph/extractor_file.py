from __future__ import annotations

from pathlib import Path


def parse_source_file(file_path: Path):
    from codegraph.extractor import parse_file

    return parse_file(file_path)


def extract_file_graph(project_root: Path, file_path: Path):
    from codegraph.extractor import extract_file

    return extract_file(project_root, file_path)
