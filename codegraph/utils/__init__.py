"""codegraph.utils — General-purpose utilities (package).

Re-exports every public name so that ``from codegraph.utils import hash_file``
continues to work after the split from monolithic utils.py to sub-modules.
"""

from codegraph.utils.file_discovery import discover_source_files
from codegraph.utils.formatting import format_json, iso_now, parse_iso
from codegraph.utils.hashing import compute_body_hash, hash_file
from codegraph.utils.ids import generate_node_id, normalize_path
from codegraph.utils.progress import ProgressReporter

__all__ = [
    "compute_body_hash",
    "discover_source_files",
    "format_json",
    "generate_node_id",
    "hash_file",
    "iso_now",
    "normalize_path",
    "parse_iso",
    "ProgressReporter",
]
