"""codegraph.utils.progress — Progress reporting for long-running operations.

(Task A-030)
"""

from __future__ import annotations

import json
import sys
import time
from typing import IO, Optional


class ProgressReporter:
    """Simple progress reporting for long-running operations.

    Parameters
    ----------
    total:
        Expected number of work items.  ``None`` for indeterminate.
    label:
        Prefix label for the progress line.
    json_mode:
        If *True*, emit JSON events to *stream* instead of a progress bar.
    stream:
        Output stream (default: ``sys.stderr``).
    """

    def __init__(
        self,
        total: Optional[int] = None,
        label: str = "Progress",
        json_mode: bool = False,
        stream: Optional[IO[str]] = None,
    ) -> None:
        self.total = total
        self.label = label
        self.json_mode = json_mode
        self.stream = stream or sys.stderr
        self._current = 0
        self._start = time.monotonic()

    def update(self, n: int = 1) -> None:
        """Advance the counter by *n* items and display progress."""
        self._current += n
        if self.json_mode:
            event = {
                "event": "progress",
                "label": self.label,
                "current": self._current,
                "total": self.total,
                "elapsed_s": round(time.monotonic() - self._start, 2),
            }
            self.stream.write(json.dumps(event) + "\n")
            self.stream.flush()
        else:
            if self.total:
                pct = int(100 * self._current / self.total)
                self.stream.write(f"\r{self.label}: {self._current}/{self.total} ({pct}%)")
            else:
                self.stream.write(f"\r{self.label}: {self._current} …")
            self.stream.flush()

    def finish(self) -> None:
        """Mark the operation as complete."""
        elapsed = round(time.monotonic() - self._start, 2)
        if self.json_mode:
            event = {
                "event": "progress_done",
                "label": self.label,
                "total": self._current,
                "elapsed_s": elapsed,
            }
            self.stream.write(json.dumps(event) + "\n")
        else:
            self.stream.write(f"\r{self.label}: done ({self._current} items, {elapsed}s)\n")
        self.stream.flush()
