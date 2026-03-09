"""Trade execution module — sample trading project.

(Task A-036)
"""

from __future__ import annotations

from typing import Any, Dict

from src.signal import generate_signal


def validate_trade(order: Dict[str, Any]) -> bool:
    """Return *True* when *order* carries mandatory fields with sane values."""
    return bool(order.get("quantity", 0) > 0 and "symbol" in order)


def execute_order(order: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a validated trade order.

    Raises
    ------
    ValueError
        If *order* fails validation.
    """
    if not validate_trade(order):
        raise ValueError("Invalid order")
    signal = generate_signal(order["symbol"])
    return {"status": "executed", "signal": signal, "order": order}
