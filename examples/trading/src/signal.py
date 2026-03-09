"""Signal generation module — sample trading project.

(Task A-036)
"""

from __future__ import annotations

from src.data import fetch_data


def generate_signal(symbol: str) -> str:
    """Derive a simple momentum signal from the last two closes.

    Returns ``"buy"`` when the latest close exceeds the prior close,
    otherwise ``"hold"``.
    """
    data = fetch_data(symbol)
    closes = data["close"]
    if len(closes) >= 2 and closes[-1] > closes[-2]:
        return "buy"
    return "hold"
