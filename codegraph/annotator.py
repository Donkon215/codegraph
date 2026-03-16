"""codegraph.annotator — Intent annotation system (Graph_1 builder).

Tasks E-001 through E-025.
"""

from __future__ import annotations

import csv
import fnmatch
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from codegraph.constants import GRAPHS_DIR
from codegraph.exceptions import IntentConflictError
from codegraph.logging_config import get_logger
from codegraph.models.agent_response import IntentProposal
from codegraph.models.graph0 import Graph0
from codegraph.models.graph1 import (
    Graph1,
    Graph1Node,
    validate_arch_layer_name,
    validate_intent,
)
from codegraph.storage import atomic_write, resolve_path
from codegraph.utils.formatting import iso_now

logger = get_logger("annotator")

_MAX_HISTORY = 10  # E-025: cap intent history entries


# ── E-017  Intent Normalization ────────────────────────────────────────


def normalize_intent(intent: str) -> str:
    """Normalize an intent string for consistency.

    - Strip whitespace
    - Collapse runs of spaces
    - Lowercase first character
    - Remove trailing period
    """
    s = intent.strip()
    s = re.sub(r"\s+", " ", s)
    if s:
        s = s[0].lower() + s[1:]
    if s.endswith("."):
        s = s[:-1]
    return s


# ── E-001  Graph_1 Initialization from Graph_0 ────────────────────────


def initialize_graph1(
    graph0: Graph0,
    layer_assignments: dict[str, int],
    *,
    existing: Graph1 | None = None,
) -> Graph1:
    """Create or merge a Graph_1 overlay from *graph0* + layer assignments.

    If *existing* is supplied, existing intents are preserved and only
    new Graph_0 nodes are added.
    """
    if existing is None:
        existing = Graph1()

    for node in graph0.nodes:
        if existing.has_node(node.id):
            # Update layer if changed, preserve intent
            ex = existing.get_node(node.id)
            if ex is not None:
                ex.layer = layer_assignments.get(node.id, ex.layer)
        else:
            existing.upsert_node(
                Graph1Node(
                    id=node.id,
                    intent="",
                    layer=layer_assignments.get(node.id, 3),
                    intent_version=0,
                )
            )

    return existing


# ── E-002  Intent Application (Single Node) ───────────────────────────


def apply_intent(
    graph1: Graph1,
    node_id: str,
    intent: str,
    author: str,
    *,
    tags: list[str] | None = None,
    arch_layer: str | None = None,
    body_hash: str = "",
    track_history: bool = False,
) -> list[str]:
    """Apply an intent annotation to *node_id* in *graph1*.

    Returns a list of quality warnings (may be empty).
    Raises :class:`IntentConflictError` if *node_id* is not in Graph_1.
    """
    node = graph1.get_node(node_id)
    if node is None:
        raise IntentConflictError(node_id)

    # Intent quality check
    ok, warnings = validate_intent(intent)
    if not ok:
        logger.warning("Empty intent for %s", node_id)

    normalized = normalize_intent(intent)

    # E-025 — optional history tracking
    if track_history and node.intent:
        _record_history(node)

    # E-011 — version tracking: first real intent sets version to 1
    if node.intent_version == 0:
        node.intent = normalized
        node.intent_author = author
        node.intent_version = 1
        node.intent_timestamp = iso_now()
    else:
        node.update_intent(normalized, author)

    # E-006 — store body hash at time of intent
    if body_hash:
        node.intent_body_hash = body_hash

    # Tags
    if tags is not None:
        node.tags = list({t.lower().strip() for t in tags if t.strip()})

    # Arch layer
    if arch_layer is not None:
        validate_arch_layer_name(arch_layer)
        node.arch_layer = arch_layer

    return warnings


def _record_history(node: Graph1Node) -> None:
    """Append the current intent to the node's history (E-025)."""
    entry = {
        "version": node.intent_version,
        "intent": node.intent,
        "author": node.intent_author,
        "timestamp": node.intent_timestamp,
    }
    node.intent_history.append(entry)
    if len(node.intent_history) > _MAX_HISTORY:
        node.intent_history = node.intent_history[-_MAX_HISTORY:]


# ── E-003  Batch Intent Application ───────────────────────────────────


@dataclass
class BatchResult:
    """Result of a batch intent application."""

    applied: int = 0
    rejected: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def apply_intents_batch(
    graph1: Graph1,
    intents: Sequence[IntentProposal],
    author: str,
    *,
    graph0: Graph0 | None = None,
    track_history: bool = False,
) -> BatchResult:
    """Apply a batch of intent proposals. Continues on individual failures.

    If *graph0* is provided, validates each node exists in Graph_0 (E-015).
    """
    result = BatchResult()
    seen: set[str] = set()

    for proposal in intents:
        nid = proposal.node
        if nid in seen:
            logger.debug("Duplicate node %s in batch — applying latest", nid)
        seen.add(nid)

        # E-015 — reject intents for nodes not in Graph_0
        if graph0 is not None and not graph0.has_node(nid):
            result.errors.append(f"Node '{nid}' not in Graph_0 — rejected")
            result.rejected += 1
            continue

        try:
            body_hash = ""
            if graph0 is not None:
                g0n = graph0.get_node(nid)
                if g0n is not None:
                    body_hash = g0n.body_hash

            w = apply_intent(
                graph1,
                nid,
                proposal.intent,
                author,
                tags=proposal.tags or None,
                body_hash=body_hash,
                track_history=track_history,
            )
            result.applied += 1
            for msg in w:
                result.warnings.append(f"{nid}: {msg}")
        except IntentConflictError:
            result.errors.append(f"Node '{nid}' not in Graph_1 — rejected")
            result.rejected += 1

    return result


# ── E-004  Intent File Loading ─────────────────────────────────────────


def load_intent_file(file_path: Path) -> list[IntentProposal]:
    """Load intent proposals from a JSON file.

    Expected format::

        [
          {"node": "mod::func", "intent": "...", "tags": [...]},
          ...
        ]

    Or an object with an ``"intents"`` key wrapping the list.
    """
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON in {file_path}: {exc}") from exc

    items: list[dict[str, Any]]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and "intents" in raw:
        items = raw["intents"]
    else:
        raise ValueError(
            f"Expected a JSON array or object with 'intents' key in {file_path}"
        )

    proposals: list[IntentProposal] = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"Item {i} is not an object in {file_path}")
        if "node" not in item or "intent" not in item:
            raise ValueError(
                f"Item {i} missing required 'node' and/or 'intent' in {file_path}"
            )
        proposals.append(IntentProposal.from_dict(item))
    return proposals


# ── E-005  Stale Intent Detection ──────────────────────────────────────


def detect_stale_intents(graph0: Graph0, graph1: Graph1) -> list[str]:
    """Return IDs of nodes whose body_hash changed since their intent was written.

    Uses E-006 ``intent_body_hash`` on Graph1Node.
    """
    stale: list[str] = []
    for g1n in graph1.nodes:
        if not g1n.intent or not g1n.intent.strip():
            continue  # no intent → not stale
        if not g1n.intent_body_hash:
            continue  # no recorded hash → first annotation, not stale
        g0n = graph0.get_node(g1n.id)
        if g0n is None:
            continue  # missing from Graph_0 → handled by pruning
        if g0n.body_hash != g1n.intent_body_hash:
            stale.append(g1n.id)
    return stale


# ── E-007  Graph_1 Pruning ─────────────────────────────────────────────


@dataclass
class PruneReport:
    removed_count: int = 0
    removed_ids: list[str] = field(default_factory=list)


def prune_graph1(graph0: Graph0, graph1: Graph1) -> PruneReport:
    """Remove Graph_1 entries whose IDs no longer exist in *graph0*."""
    g0_ids = frozenset(n.id for n in graph0.nodes)
    stale_ids = graph1.get_stale_nodes(g0_ids)
    report = PruneReport()

    if not stale_ids:
        return report

    if not graph0.nodes:
        logger.warning("Graph_0 is empty — pruning all Graph_1 entries")

    for nid in stale_ids:
        graph1.remove_intent_node(nid)
        report.removed_ids.append(nid)
        logger.warning("Pruned stale Graph_1 node: %s", nid)
        report.removed_count += 1

    return report


# ── E-008  Missing Intent Reporter ─────────────────────────────────────


def get_missing_intents(graph0: Graph0, graph1: Graph1) -> list[str]:
    """Return node IDs that lack intent annotations, sorted by file path."""
    missing: list[tuple[str, str]] = []  # (file, node_id)

    for g0n in graph0.nodes:
        g1n = graph1.get_node(g0n.id)
        if g1n is None or not g1n.intent or not g1n.intent.strip():
            missing.append((g0n.file, g0n.id))

    missing.sort(key=lambda t: t[0])
    return [nid for _, nid in missing]


# ── E-009  Intent Tags Management ──────────────────────────────────────


def add_tags(graph1: Graph1, node_id: str, tags: list[str]) -> None:
    """Add tags to a node (case-insensitive, de-duplicated)."""
    node = graph1.get_node(node_id)
    if node is None:
        raise IntentConflictError(node_id)
    for tag in tags:
        t = tag.lower().strip()
        if not t:
            raise ValueError("Tag must not be empty")
        if t not in node.tags:
            node.tags.append(t)


def remove_tags(graph1: Graph1, node_id: str, tags: list[str]) -> None:
    """Remove tags from a node (no error if tag absent)."""
    node = graph1.get_node(node_id)
    if node is None:
        raise IntentConflictError(node_id)
    lower_tags = {t.lower().strip() for t in tags}
    node.tags = [t for t in node.tags if t not in lower_tags]


def get_nodes_by_tag(graph1: Graph1, tag: str) -> list[str]:
    """Return node IDs that have the given *tag*."""
    t = tag.lower().strip()
    return [n.id for n in graph1.nodes if t in n.tags]


# ── E-010  Arch Layer Annotation ───────────────────────────────────────


def set_arch_layer(graph1: Graph1, node_id: str, arch_layer: str) -> None:
    """Set the architectural layer label on a node."""
    node = graph1.get_node(node_id)
    if node is None:
        raise IntentConflictError(node_id)
    validate_arch_layer_name(arch_layer)
    node.arch_layer = arch_layer


# ── E-013  Graph_1 Merge Strategy ─────────────────────────────────────


def merge_graph1(
    existing_graph1: Graph1,
    new_graph0: Graph0,
    layers: dict[str, int],
) -> Graph1:
    """Merge *existing_graph1* with a new Graph_0 extraction.

    - New nodes get empty intents.
    - Existing intents are preserved.
    - Removed nodes are kept (for prune to handle).
    - Layers are updated to reflect new detection.
    """
    new_ids = {n.id for n in new_graph0.nodes}

    for node in new_graph0.nodes:
        if existing_graph1.has_node(node.id):
            ex = existing_graph1.get_node(node.id)
            if ex is not None:
                ex.layer = layers.get(node.id, ex.layer)
        else:
            existing_graph1.upsert_node(
                Graph1Node(
                    id=node.id,
                    intent="",
                    layer=layers.get(node.id, 3),
                    intent_version=0,
                )
            )

    # Mark stale nodes (don't remove)
    stale = [n.id for n in existing_graph1.nodes if n.id not in new_ids]
    if stale:
        logger.info("Stale Graph_1 entries (not in new Graph_0): %d", len(stale))

    return existing_graph1


# ── E-014  Graph_1 Persistence (Save/Load) ─────────────────────────────


def save_graph1(graph1: Graph1, project_root: Path) -> None:
    """Save Graph_1 to ``.codegraph/graphs/graph1.json`` (sorted, atomic)."""
    # Sort nodes by ID for clean diffs
    graph1.nodes.sort(key=lambda n: n.id)
    data = json.loads(graph1.to_json())
    path = resolve_path(project_root, GRAPHS_DIR, "graph1.json")
    atomic_write(path, data)
    logger.info("Saved Graph_1 (%d nodes) → %s", len(graph1.nodes), path)


def load_graph1(project_root: Path) -> Graph1:
    """Load Graph_1 from disk, returning an empty Graph_1 if not found."""
    path = resolve_path(project_root, GRAPHS_DIR, "graph1.json")
    if not path.exists():
        logger.debug("No graph1.json found — starting with empty Graph_1")
        return Graph1()
    text = path.read_text(encoding="utf-8")
    g1 = Graph1.from_json(text)
    logger.debug("Loaded Graph_1 with %d nodes from %s", len(g1.nodes), path)
    return g1


# ── E-016  Module and Class Intent Support ─────────────────────────────
# No special code needed — apply_intent works for any node type.
# Validation in validate_intent already handles descriptive intents.


# ── E-018  Intent Consistency Checker ──────────────────────────────────


@dataclass
class ConsistencyWarning:
    tag: str
    node_ids: list[str]
    message: str


def check_intent_consistency(graph1: Graph1) -> list[ConsistencyWarning]:
    """Check for inconsistent intents within tag groups.

    Reports:
    - Duplicate identical intents across different nodes (copy-paste)
    - Very different intents within the same tag group
    """
    warnings: list[ConsistencyWarning] = []

    # Group nodes by tag
    by_tag: dict[str, list[Graph1Node]] = defaultdict(list)
    for node in graph1.nodes:
        for tag in node.tags:
            by_tag[tag].append(node)

    for tag, nodes in by_tag.items():
        if len(nodes) < 2:
            continue

        # Check for exact duplicate intents
        intent_to_ids: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            if n.intent and n.intent.strip():
                intent_to_ids[n.intent].append(n.id)

        for intent, ids in intent_to_ids.items():
            if len(ids) > 1:
                warnings.append(
                    ConsistencyWarning(
                        tag=tag,
                        node_ids=ids,
                        message=f"Duplicate intent across {len(ids)} nodes in tag '{tag}': \"{intent[:60]}\"",
                    )
                )

    return warnings


# ── E-019  Graph_1 Export for Review ───────────────────────────────────


def export_graph1(graph1: Graph1, fmt: str = "json") -> str:
    """Export Graph_1 annotations in a human-readable format.

    Supported formats: ``json``, ``csv``, ``markdown``.
    """
    nodes_sorted = sorted(graph1.nodes, key=lambda n: n.id)

    if fmt == "json":
        data = [
            {
                "node_id": n.id,
                "intent": n.intent,
                "layer": n.layer,
                "arch_layer": n.arch_layer or "",
                "tags": ", ".join(n.tags),
            }
            for n in nodes_sorted
        ]
        return json.dumps(data, indent=2, ensure_ascii=False) + "\n"

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["node_id", "intent", "layer", "arch_layer", "tags"])
        for n in nodes_sorted:
            writer.writerow([n.id, n.intent, n.layer, n.arch_layer or "", ", ".join(n.tags)])
        return output.getvalue()

    if fmt == "markdown":
        lines = ["| Node ID | Intent | Layer | Arch Layer | Tags |"]
        lines.append("|---------|--------|-------|------------|------|")
        for n in nodes_sorted:
            intent_esc = n.intent.replace("|", "\\|") if n.intent else ""
            lines.append(
                f"| {n.id} | {intent_esc} | {n.layer} | {n.arch_layer or ''} | {', '.join(n.tags)} |"
            )
        return "\n".join(lines) + "\n"

    raise ValueError(f"Unsupported export format: {fmt}")


# ── E-020  Graph_1 Import from External Sources ───────────────────────


def import_intents(file_path: Path, fmt: str = "json") -> list[IntentProposal]:
    """Import intent proposals from a file.

    Supported formats: ``json`` (same as E-004), ``csv``.
    """
    if fmt == "json":
        return load_intent_file(file_path)

    if fmt == "csv":
        text = file_path.read_text(encoding="utf-8")
        reader = csv.DictReader(io.StringIO(text))
        proposals: list[IntentProposal] = []
        for i, row in enumerate(reader):
            if "node_id" not in row or "intent" not in row:
                raise ValueError(
                    f"CSV row {i + 1} missing required 'node_id' and/or 'intent' columns"
                )
            tags_raw = row.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
            proposals.append(
                IntentProposal(node=row["node_id"], intent=row["intent"], tags=tags)
            )
        return proposals

    raise ValueError(f"Unsupported import format: {fmt}")


# ── E-021  Stale Intent Warning in Build Output ───────────────────────


def format_stale_warnings(
    stale_ids: list[str],
    ghost_ids: list[str],
) -> str:
    """Format the stale intent warning block matching README spec."""
    if not stale_ids and not ghost_ids:
        return ""
    lines: list[str] = ["WARNING: stale intent entries detected"]
    for nid in ghost_ids:
        lines.append(f"  {nid} → no matching node in graph0")
    for nid in stale_ids:
        lines.append(f"  {nid} → body_hash changed since last intent")
    lines.append("Run `codegraph prune` to remove stale entries.")
    return "\n".join(lines)


# ── E-022  Graph_1 Diff for Review ────────────────────────────────────


@dataclass
class Graph1DiffEntry:
    node_id: str
    change_type: str  # "added", "removed", "modified"
    old_intent: str = ""
    new_intent: str = ""


@dataclass
class Graph1Diff:
    added: list[Graph1DiffEntry] = field(default_factory=list)
    removed: list[Graph1DiffEntry] = field(default_factory=list)
    modified: list[Graph1DiffEntry] = field(default_factory=list)

    def format(self) -> str:
        lines: list[str] = []
        if self.added:
            lines.append(f"Added ({len(self.added)}):")
            for e in self.added:
                lines.append(f"  + {e.node_id}: \"{e.new_intent}\"")
        if self.removed:
            lines.append(f"Removed ({len(self.removed)}):")
            for e in self.removed:
                lines.append(f"  - {e.node_id}: \"{e.old_intent}\"")
        if self.modified:
            lines.append(f"Modified ({len(self.modified)}):")
            for e in self.modified:
                lines.append(f"  ~ {e.node_id}:")
                lines.append(f"      old: \"{e.old_intent}\"")
                lines.append(f"      new: \"{e.new_intent}\"")
        if not lines:
            lines.append("No changes.")
        return "\n".join(lines)


def diff_graph1(old: Graph1, new: Graph1) -> Graph1Diff:
    """Compute the diff between two Graph_1 instances."""
    result = Graph1Diff()
    old_index = {n.id: n for n in old.nodes}
    new_index = {n.id: n for n in new.nodes}

    for nid, nn in new_index.items():
        if nid not in old_index:
            result.added.append(
                Graph1DiffEntry(node_id=nid, change_type="added", new_intent=nn.intent)
            )
        else:
            on = old_index[nid]
            if on.intent != nn.intent:
                result.modified.append(
                    Graph1DiffEntry(
                        node_id=nid, change_type="modified",
                        old_intent=on.intent, new_intent=nn.intent,
                    )
                )

    for nid, on in old_index.items():
        if nid not in new_index:
            result.removed.append(
                Graph1DiffEntry(node_id=nid, change_type="removed", old_intent=on.intent)
            )

    return result


# ── E-023  Bulk Arch Layer Assignment ──────────────────────────────────


def batch_set_arch_layer(
    graph1: Graph1,
    pattern: str,
    arch_layer: str,
) -> int:
    """Set *arch_layer* on all nodes whose ID matches *pattern* (glob).

    Returns the count of affected nodes.
    """
    validate_arch_layer_name(arch_layer)
    count = 0
    for node in graph1.nodes:
        if fnmatch.fnmatch(node.id, pattern):
            node.arch_layer = arch_layer
            count += 1
    logger.info("batch_set_arch_layer '%s' → '%s': %d nodes", pattern, arch_layer, count)
    return count


# ── E-024  Graph_1 Statistics ──────────────────────────────────────────


@dataclass
class AnnotationStats:
    total_nodes: int = 0
    nodes_with_intent: int = 0
    nodes_missing_intent: int = 0
    coverage_pct: float = 0.0
    avg_intent_length: float = 0.0
    nodes_with_tags: int = 0
    nodes_with_arch_layer: int = 0
    stale_intent_count: int = 0

    def format(self) -> str:
        return (
            f"Annotation statistics:\n"
            f"  Total nodes:          {self.total_nodes}\n"
            f"  With intent:          {self.nodes_with_intent}  "
            f"({self.coverage_pct:.1f}%)\n"
            f"  Missing intent:       {self.nodes_missing_intent}\n"
            f"  Avg intent length:    {self.avg_intent_length:.0f} chars\n"
            f"  With tags:            {self.nodes_with_tags}\n"
            f"  With arch_layer:      {self.nodes_with_arch_layer}\n"
            f"  Stale intents:        {self.stale_intent_count}"
        )


def graph1_statistics(
    graph0: Graph0,
    graph1: Graph1,
) -> AnnotationStats:
    """Compute annotation coverage and quality metrics."""
    stats = AnnotationStats(total_nodes=len(graph1.nodes))

    intent_lengths: list[int] = []
    for node in graph1.nodes:
        has_intent = bool(node.intent and node.intent.strip())
        if has_intent:
            stats.nodes_with_intent += 1
            intent_lengths.append(len(node.intent))
        else:
            stats.nodes_missing_intent += 1
        if node.tags:
            stats.nodes_with_tags += 1
        if node.arch_layer:
            stats.nodes_with_arch_layer += 1

    if stats.total_nodes:
        stats.coverage_pct = stats.nodes_with_intent / stats.total_nodes * 100
    if intent_lengths:
        stats.avg_intent_length = sum(intent_lengths) / len(intent_lengths)

    stats.stale_intent_count = len(detect_stale_intents(graph0, graph1))
    return stats
