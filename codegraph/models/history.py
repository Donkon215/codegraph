"""codegraph.models.history — Response & task history manager.

Task B-034.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from codegraph.constants import CODEGRAPH_DIR, RESPONSES_DIR, TASKS_DIR
from codegraph.logging_config import get_logger
from codegraph.models.agent_response import AgentResponse
from codegraph.models.tasks import TaskBatch
from codegraph.storage import atomic_write

logger = get_logger("models.history")


class ResponseHistoryManager:
    """Persist and retrieve historical task batches and agent responses.

    Files are stored under ``.codegraph/tasks/`` and ``.codegraph/responses/``
    with cycle-numbered filenames.
    """

    def __init__(self, project_root: Path) -> None:
        self._root = project_root
        self._tasks_dir = project_root / CODEGRAPH_DIR / TASKS_DIR
        self._resp_dir = project_root / CODEGRAPH_DIR / RESPONSES_DIR
        self._tasks_dir.mkdir(parents=True, exist_ok=True)
        self._resp_dir.mkdir(parents=True, exist_ok=True)

    # ── Tasks ─────────────────────────────────────────────────────────

    def save_tasks(self, batch: TaskBatch) -> Path:
        fp = self._tasks_dir / f"tasks_{batch.cycle}.json"
        atomic_write(fp, batch.to_json())
        return fp

    def load_tasks(self, cycle: int) -> Optional[TaskBatch]:
        fp = self._tasks_dir / f"tasks_{cycle}.json"
        if not fp.exists():
            return None
        return TaskBatch.from_json(fp.read_text(encoding="utf-8"))

    # ── Responses ─────────────────────────────────────────────────────

    def save_response(self, response: AgentResponse) -> Path:
        fp = self._resp_dir / f"response_{response.cycle}.json"
        atomic_write(fp, response.to_json())
        return fp

    def load_response(self, cycle: int) -> Optional[AgentResponse]:
        fp = self._resp_dir / f"response_{cycle}.json"
        if not fp.exists():
            return None
        return AgentResponse.from_json(fp.read_text(encoding="utf-8"))

    # ── Listing ───────────────────────────────────────────────────────

    def list_cycles(self) -> List[int]:
        """Return sorted list of all cycle numbers that have saved tasks."""
        cycles: List[int] = []
        for f in self._tasks_dir.glob("tasks_*.json"):
            stem = f.stem  # tasks_3
            try:
                cycles.append(int(stem.split("_", 1)[1]))
            except (IndexError, ValueError):
                pass
        cycles.sort()
        return cycles
