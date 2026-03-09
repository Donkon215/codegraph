"""Shared pytest fixtures for codegraph tests.

(Task A-015)
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest

from codegraph.config import CodegraphConfig
from codegraph.storage import ensure_codegraph_dir


# ── Sample Python source ───────────────────────────────────────────────

_DATA_PY = textwrap.dedent("""\
    \"\"\"Data fetching module.\"\"\"

    import requests


    def fetch_data(symbol: str, timeframe: str = "1d") -> dict:
        \"\"\"Fetch OHLCV market data from exchange REST API.\"\"\"
        url = f"https://api.exchange.com/ohlcv/{symbol}"
        response = requests.get(url, params={"tf": timeframe})
        response.raise_for_status()
        return response.json()
""")

_SIGNAL_PY = textwrap.dedent("""\
    \"\"\"Signal generation module.\"\"\"

    from src.data import fetch_data


    def generate_signal(symbol: str) -> str:
        \"\"\"Generate trading signal from price indicators.\"\"\"
        data = fetch_data(symbol)
        if data["close"][-1] > data["close"][-2]:
            return "buy"
        return "hold"
""")

_TRADE_PY = textwrap.dedent("""\
    \"\"\"Trade execution module.\"\"\"

    from src.signal import generate_signal


    def validate_trade(order: dict) -> bool:
        \"\"\"Validate that a trade order meets requirements.\"\"\"
        return order.get("quantity", 0) > 0 and "symbol" in order


    def execute_order(order: dict) -> dict:
        \"\"\"Execute validated trade order on exchange.\"\"\"
        if not validate_trade(order):
            raise ValueError("Invalid order")
        signal = generate_signal(order["symbol"])
        return {"status": "executed", "signal": signal, "order": order}
""")

_TEST_TRADE_PY = textwrap.dedent("""\
    \"\"\"Tests for trade module.\"\"\"

    from src.trade import validate_trade, execute_order


    def test_validate_trade_valid():
        assert validate_trade({"symbol": "BTC", "quantity": 1})


    def test_validate_trade_invalid():
        assert not validate_trade({})
""")


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal sample project in a temp directory."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "data.py").write_text(_DATA_PY, encoding="utf-8")
    (src / "signal.py").write_text(_SIGNAL_PY, encoding="utf-8")
    (src / "trade.py").write_text(_TRADE_PY, encoding="utf-8")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_trade.py").write_text(_TEST_TRADE_PY, encoding="utf-8")

    # Create a pyproject.toml so project root detection works.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "sample"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def initialized_project(tmp_project: Path) -> Path:
    """A sample project with ``.codegraph/`` already initialized."""
    ensure_codegraph_dir(tmp_project)
    return tmp_project


@pytest.fixture()
def sample_graph0() -> Dict[str, Any]:
    """A minimal graph0.json dict for testing."""
    return {
        "format_version": 1,
        "graph_version": 1,
        "nodes": [
            {
                "id": "src/data.py::fetch_data",
                "body_hash": "c72b4",
                "file": "src/data.py",
                "type": "function",
                "line": 6,
            },
            {
                "id": "src/signal.py::generate_signal",
                "body_hash": "8f1c2",
                "file": "src/signal.py",
                "type": "function",
                "line": 6,
            },
            {
                "id": "src/trade.py::validate_trade",
                "body_hash": "aa1b3",
                "file": "src/trade.py",
                "type": "function",
                "line": 6,
            },
            {
                "id": "src/trade.py::execute_order",
                "body_hash": "3a9d1",
                "file": "src/trade.py",
                "type": "function",
                "line": 12,
            },
        ],
    }


@pytest.fixture()
def sample_graph1() -> Dict[str, Any]:
    """A minimal graph1.json dict for testing."""
    return {
        "format_version": 1,
        "nodes": [
            {
                "id": "src/data.py::fetch_data",
                "intent": "fetch OHLCV market data from exchange REST API",
                "layer": 3,
            },
            {
                "id": "src/signal.py::generate_signal",
                "intent": "generate trading signal from price indicators",
                "layer": 3,
            },
            {
                "id": "src/trade.py::execute_order",
                "intent": "execute validated trade order on exchange",
                "layer": 3,
            },
        ],
    }


@pytest.fixture()
def sample_workflow() -> Dict[str, Any]:
    """A minimal workflow.json dict for testing."""
    return {
        "format_version": 1,
        "edges": [
            {
                "source": "src/data.py::fetch_data",
                "target": "src/signal.py::generate_signal",
                "edge_type": "call",
                "confidence": "static",
            },
            {
                "source": "src/signal.py::generate_signal",
                "target": "src/trade.py::execute_order",
                "edge_type": "call",
                "confidence": "static",
            },
            {
                "source": "src/trade.py::execute_order",
                "target": "src/trade.py::validate_trade",
                "edge_type": "call",
                "confidence": "static",
            },
        ],
    }


# ── Assertion helpers ──────────────────────────────────────────────────


def assert_valid_json(text: str) -> Any:
    """Parse *text* as JSON and return the decoded object; fail if invalid."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Invalid JSON: {exc}")


def assert_has_keys(d: Dict[str, Any], *keys: str) -> None:
    """Assert that *d* contains all *keys*."""
    missing = [k for k in keys if k not in d]
    if missing:
        pytest.fail(f"Missing keys: {missing}")
