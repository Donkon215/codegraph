"""Data fetching module — sample trading project.

This is the **example** project shipped with codegraph.  Run
``codegraph build`` from the ``examples/trading`` directory to see
codegraph produce the full Graph-0 / Graph-1 / Workflow output.

(Task A-036)
"""

from __future__ import annotations

from typing import Any, Dict


def fetch_data(symbol: str, timeframe: str = "1d") -> Dict[str, Any]:
    """Fetch OHLCV market data from exchange REST API.

    Parameters
    ----------
    symbol:
        Ticker symbol, e.g. ``"BTC"``.
    timeframe:
        Candle period (``"1m"``, ``"1h"``, ``"1d"``).

    Returns
    -------
    dict
        Keys ``open``, ``high``, ``low``, ``close``, ``volume`` –
        each a list of floats.
    """
    # In a real project this would call an exchange REST endpoint.
    # Stubbed here so the example is self-contained.
    return {
        "open": [100.0, 101.0, 102.0],
        "high": [105.0, 106.0, 107.0],
        "low": [99.0, 100.0, 101.0],
        "close": [104.0, 105.0, 106.0],
        "volume": [1000.0, 1100.0, 1200.0],
    }
