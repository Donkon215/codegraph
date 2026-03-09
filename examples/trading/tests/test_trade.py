"""Tests for the trade module — sample trading project.

(Task A-036)
"""

from __future__ import annotations

import pytest

from src.trade import execute_order, validate_trade


class TestValidateTrade:
    def test_valid_order(self) -> None:
        assert validate_trade({"symbol": "BTC", "quantity": 1})

    def test_missing_symbol(self) -> None:
        assert not validate_trade({"quantity": 1})

    def test_zero_quantity(self) -> None:
        assert not validate_trade({"symbol": "ETH", "quantity": 0})

    def test_empty_dict(self) -> None:
        assert not validate_trade({})


class TestExecuteOrder:
    def test_valid_execution(self) -> None:
        result = execute_order({"symbol": "BTC", "quantity": 1})
        assert result["status"] == "executed"
        assert result["signal"] in ("buy", "hold")

    def test_invalid_order_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid order"):
            execute_order({})
