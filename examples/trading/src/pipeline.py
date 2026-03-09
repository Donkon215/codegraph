"""Pipeline orchestration — sample trading project.

(Task A-036)
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.data import fetch_data
from src.signal import generate_signal
from src.trade import execute_order


def run_pipeline(symbols: List[str]) -> List[Dict[str, Any]]:
    """Run the full data → signal → trade pipeline for each symbol."""
    results: List[Dict[str, Any]] = []
    for symbol in symbols:
        data = fetch_data(symbol)
        signal = generate_signal(symbol)
        if signal == "buy":
            order = {"symbol": symbol, "quantity": 1}
            result = execute_order(order)
        else:
            result = {"status": "skipped", "signal": signal, "symbol": symbol}
        results.append(result)
    return results


if __name__ == "__main__":
    outcomes = run_pipeline(["BTC", "ETH", "SOL"])
    for o in outcomes:
        print(o)
