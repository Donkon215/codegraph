#!/usr/bin/env bash
# Record CodeGraph CLI demo as GIF
# Requires: asciinema (for recording) + agg (for GIF conversion)
# Install: pip install asciinema agg

set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEMO_DIR="$REPO_ROOT/assets"
CAST_FILE="$DEMO_DIR/demo.cast"
GIF_FILE="$DEMO_DIR/demo.gif"

echo "🎬 Recording CodeGraph CLI demo..."
echo "Repository: $REPO_ROOT"
echo "Output: $GIF_FILE"
echo ""

# Create a clean sample project for recording
SAMPLE_DIR=$(mktemp -d -t codegraph-demo-XXXXXX)
echo "📁 Using temp directory: $SAMPLE_DIR"

# Copy sample project
cp -r "$REPO_ROOT/../sample_project"/* "$SAMPLE_DIR/" 2>/dev/null || true

# Ensure we have a clean sample project
mkdir -p "$SAMPLE_DIR/src/trading" "$SAMPLE_DIR/src/data" "$SAMPLE_DIR/src/execution" "$SAMPLE_DIR/tests"

cat > "$SAMPLE_DIR/src/data/market.py" << 'EOF'
"""Market data fetching module."""
import requests
from typing import List, Dict, Any
from datetime import datetime

def fetch_market_data(symbol: str, timeframe: str = "1m", limit: int = 100) -> List[Dict[str, Any]]:
    """Fetch OHLCV market data from exchange REST API."""
    url = f"https://api.exchange.com/v1/klines"
    params = {"symbol": symbol, "interval": timeframe, "limit": limit}
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    return response.json()

def parse_kline(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Parse raw kline data into structured format."""
    return {
        "timestamp": datetime.fromtimestamp(raw[0] / 1000),
        "open": float(raw[1]),
        "high": float(raw[2]),
        "low": float(raw[3]),
        "close": float(raw[4]),
        "volume": float(raw[5]),
    }

def fetch_recent_klines(symbol: str, count: int = 50) -> List[Dict[str, Any]]:
    """Fetch and parse recent klines for a symbol."""
    raw_data = fetch_market_data(symbol, limit=count)
    return [parse_kline(k) for k in raw_data]
EOF

cat > "$SAMPLE_DIR/src/trading/signal.py" << 'EOF'
"""Signal generation module."""
from typing import List, Dict, Any
import numpy as np
from src.data.market import fetch_recent_klines

def compute_rsi(prices: List[float], period: int = 14) -> float:
    """Compute Relative Strength Index."""
    if len(prices) < period + 1:
        return 50.0
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains[-period:])
    avg_loss = np.mean(losses[-period:])
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def compute_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
    """Compute MACD indicator."""
    ema_fast = np.mean(prices[-fast:])
    ema_slow = np.mean(prices[-slow:])
    macd_line = ema_fast - ema_slow
    signal_line = np.mean(prices[-signal:])
    return {"macd": macd_line, "signal": signal_line, "histogram": macd_line - signal_line}

def generate_signal(symbol: str) -> Dict[str, Any]:
    """Generate trading signal from price indicators."""
    klines = fetch_recent_klines(symbol, count=100)
    closes = [k["close"] for k in klines]
    
    rsi = compute_rsi(closes)
    macd = compute_macd(closes)
    
    action = "hold"
    if rsi < 30 and macd["macd"] > macd["signal"]:
        action = "buy"
    elif rsi > 70 and macd["macd"] < macd["signal"]:
        action = "sell"
    
    return {
        "symbol": symbol,
        "action": action,
        "rsi": rsi,
        "macd": macd,
        "confidence": 0.75 if action != "hold" else 0.5,
    }
EOF

cat > "$SAMPLE_DIR/src/execution/trade.py" << 'EOF'
"""Trade execution module."""
from typing import Dict, Any
from src.trading.signal import generate_signal

def validate_trade(signal: Dict[str, Any]) -> bool:
    """Validate order size and price parameters before execution."""
    if signal.get("confidence", 0) < 0.6:
        return False
    if signal.get("action") == "hold":
        return False
    return True

def execute_order(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Execute validated trade order on exchange."""
    if not validate_trade(signal):
        return {"status": "rejected", "reason": "validation failed"}
    order_id = f"ORD_{signal['symbol']}_{hash(str(signal)) % 10000}"
    return {"status": "sent", "order_id": order_id, "symbol": signal["symbol"], "action": signal["action"]}

def run_trading_pipeline(symbol: str) -> Dict[str, Any]:
    """Run full trading pipeline: signal -> validate -> execute."""
    signal = generate_signal(symbol)
    if not validate_trade(signal):
        return {"status": "no_trade", "signal": signal}
    return execute_order(signal)
EOF

touch "$SAMPLE_DIR/src/trading/__init__.py" "$SAMPLE_DIR/src/data/__init__.py" "$SAMPLE_DIR/src/execution/__init__.py"

cat > "$SAMPLE_DIR/tests/test_signal.py" << 'EOF'
from src.trading.signal import compute_rsi, compute_macd, generate_signal

def test_compute_rsi():
    prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 115]
    rsi = compute_rsi(prices)
    assert 0 <= rsi <= 100

def test_compute_macd():
    prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109, 110, 112, 111, 113, 115]
    macd = compute_macd(prices)
    assert "macd" in macd
    assert "signal" in macd

def test_generate_signal():
    signal = generate_signal("BTCUSDT")
    assert "action" in signal
    assert signal["action"] in ["buy", "sell", "hold"]
EOF

cd "$SAMPLE_DIR"
pip install numpy requests -q 2>/dev/null

# Record the session
echo "🔴 Recording asciinema cast..."
asciinema rec -c "bash -c '
export PYTHONPATH=\"'$REPO_ROOT'\"
export PYTHONIOENCODING=utf-8

# Clear screen and show prompt
clear
echo \"# CodeGraph CLI Demo\"
echo \"\"
echo \"\$ codegraph init\"
python -m codegraph init
echo \"\"
echo \"\$ codegraph build\"
python -m codegraph build
echo \"\"
echo \"\$ codegraph status\"
python -m codegraph status
echo \"\"
echo \"\$ codegraph intent-missing\"
python -m codegraph intent-missing
echo \"\"
echo \"\$ codegraph tasks\"
python -m codegraph tasks
echo \"\"
echo \"\$ codegraph explain src/trading/signal.py::generate_signal\"
python -m codegraph explain src/trading/signal.py::generate_signal 2>/dev/null || echo \"(explain needs query engine)\"
echo \"\"
echo \"\$ codegraph intent-apply intents.json\"
python -m codegraph intent-apply ../intents.json
echo \"\"
echo \"\$ codegraph delta\"
python -m codegraph delta
echo \"\"
echo \"\$ codegraph analyze\"
python -m codegraph analyze
' \"$CAST_FILE\"

# Convert to GIF
echo "🎞️  Converting to GIF..."
agg --font-size 14 --theme solarized-dark --speed 2 "$CAST_FILE" "$GIF_FILE"

echo "✅ Done! GIF saved to $GIF_FILE"
echo "   Cast file saved to $CAST_FILE (for re-rendering)"
echo ""
echo "To view the cast: asciinema play $CAST_FILE"
echo "To re-render GIF: agg --font-size 14 --theme solarized-dark --speed 2 $CAST_FILE $GIF_FILE"