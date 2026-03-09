# Sample Trading Project

A tiny but realistic Python project used as the reference example for
**codegraph**.  It has four source modules with clear call-chain
relationships and a small test file.

## Structure

```
src/
  data.py        – fetch_data()
  signal.py      – generate_signal()  → calls fetch_data
  trade.py       – validate_trade(), execute_order()  → calls generate_signal
  pipeline.py    – run_pipeline()     → orchestrates all of the above
tests/
  test_trade.py  – pytest tests for trade.py
```

## Running codegraph on this project

```bash
cd examples/trading
codegraph init
codegraph build
codegraph status
```
