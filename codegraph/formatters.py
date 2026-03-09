"""codegraph.formatters — Unified output formatting system.

Task N-020: Supports text, json, table, and csv formats for CLI output.
Respects --verbose and --quiet flags.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional, Sequence, Union

import click


class OutputFormatter:
    """Unified output formatter for CLI commands.

    Parameters
    ----------
    fmt:
        Output format: ``text``, ``json``, ``table``, ``csv``, ``count``.
    verbose:
        Show additional detail columns / nested data.
    quiet:
        Suppress non-essential output (summaries, decorations).
    color:
        Enable ANSI color codes (auto-detected if *None*).
    """

    FORMATS = ("text", "json", "table", "csv", "count")

    def __init__(
        self,
        fmt: str = "text",
        verbose: bool = False,
        quiet: bool = False,
        color: Optional[bool] = None,
    ) -> None:
        if fmt not in self.FORMATS:
            raise ValueError(f"Unknown format '{fmt}'; choose from {self.FORMATS}")
        self.fmt = fmt
        self.verbose = verbose
        self.quiet = quiet
        self.color = color

    # ── Public helpers ─────────────────────────────────────────────────

    def format_value(self, value: Any) -> str:
        """Format a single scalar or simple structure."""
        if self.fmt == "json":
            return json.dumps(value, indent=2, ensure_ascii=False, default=str)
        if self.fmt == "count" and isinstance(value, (list, dict)):
            return str(len(value))
        return str(value)

    def format_list(
        self,
        items: Sequence[Any],
        *,
        columns: Optional[List[str]] = None,
        key_fn: Optional[Any] = None,
    ) -> str:
        """Format a list of items (dicts or objects).

        Parameters
        ----------
        items:
            The items to format.
        columns:
            When *table* or *csv*, the column names to extract from each item.
        key_fn:
            Optional callable that converts each item to a dict.
        """
        if not items:
            return "" if self.quiet else "(empty)"

        rows: List[Dict[str, Any]] = []
        for item in items:
            if key_fn:
                rows.append(key_fn(item))
            elif isinstance(item, dict):
                rows.append(item)
            elif hasattr(item, "__dict__"):
                rows.append(vars(item))
            else:
                rows.append({"value": item})

        if self.fmt == "json":
            return json.dumps(rows, indent=2, ensure_ascii=False, default=str)

        if self.fmt == "count":
            return str(len(rows))

        if columns is None:
            columns = list(rows[0].keys()) if rows else []

        if self.fmt == "csv":
            return self._format_csv(rows, columns)

        if self.fmt == "table":
            return self._format_table(rows, columns)

        # text
        return self._format_text_list(rows, columns)

    def format_dict(self, data: Dict[str, Any]) -> str:
        """Format a single dictionary."""
        if self.fmt == "json":
            return json.dumps(data, indent=2, ensure_ascii=False, default=str)
        if self.fmt == "count":
            return str(len(data))
        lines: list[str] = []
        for k, v in data.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)

    def header(self, text: str) -> str:
        """Return a section header (suppressed in quiet/json mode)."""
        if self.quiet or self.fmt in ("json", "csv"):
            return ""
        if self.color is not False:
            return click.style(text, bold=True)
        return text

    def success(self, text: str) -> str:
        """Format a success message."""
        if self.color is not False:
            return click.style(text, fg="green")
        return text

    def warning(self, text: str) -> str:
        """Format a warning message."""
        if self.color is not False:
            return click.style(text, fg="yellow")
        return text

    def error(self, text: str) -> str:
        """Format an error message."""
        if self.color is not False:
            return click.style(text, fg="red")
        return text

    # ── Private ────────────────────────────────────────────────────────

    def _format_text_list(
        self, rows: List[Dict[str, Any]], columns: List[str],
    ) -> str:
        lines: list[str] = []
        for row in rows:
            parts: list[str] = []
            for col in columns:
                val = row.get(col, "")
                parts.append(f"{col}={val}" if self.verbose else str(val))
            lines.append("  ".join(parts))
        return "\n".join(lines)

    def _format_table(
        self, rows: List[Dict[str, Any]], columns: List[str],
    ) -> str:
        widths: dict[str, int] = {}
        for col in columns:
            widths[col] = max(
                len(col),
                max((len(str(r.get(col, ""))) for r in rows), default=0),
            )

        header = "  ".join(col.ljust(widths[col]) for col in columns)
        sep = "  ".join("-" * widths[col] for col in columns)

        lines = [header, sep]
        for row in rows:
            line = "  ".join(str(row.get(col, "")).ljust(widths[col]) for col in columns)
            lines.append(line)
        return "\n".join(lines)

    def _format_csv(
        self, rows: List[Dict[str, Any]], columns: List[str],
    ) -> str:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().rstrip("\n")
