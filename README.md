# Indian Intraday AI Trader

A beginner-friendly Streamlit paper-trading starter for Indian equities. The initial version is rule-based and uses no paid AI API.

## Features
- Streamlit dashboard
- Demo candles, best-effort Yahoo Finance candles, or uploaded OHLCV CSV
- EMA 9/21 crossover with RSI confirmation
- ATR-based indicative stop and risk-based suggested position size
- SQLite paper-trade log and CSV export
- Live trading is not implemented; no real orders are sent

## Run in GitHub Codespaces
1. Open this repository and tap Code → Codespaces → Create codespace on main.
2. In the terminal, run:

   pip install -r requirements.txt
   streamlit run app.py --server.address 0.0.0.0 --server.port 8501

3. Open forwarded port 8501 when Codespaces offers it.
4. Select Demo data first, then click Load data and scan.

## CSV format
Required columns: timestamp (or date), open, high, low, close. Volume is optional. Use one row per candle; the app sorts by timestamp.

## Important limitations
- This is a software starter, not a profitable strategy or financial advice.
- Yahoo Finance data may be delayed, unavailable, or unsuitable for live execution. It is not a guaranteed real-time broker feed.
- The first version does not run a background trading loop and does not submit live broker orders.
- Paper trades are stored in paper_trades.db in the runtime. They may be lost if the runtime is reset unless you back up the database.
- Before live trading, add an official broker API adapter, secure secrets, exchange/market-hours checks, order-state reconciliation, duplicate-order prevention, hard risk limits, logs/alerts, and a kill switch. Verify current broker terms and Indian regulatory requirements.

## Suggested next stages
1. Add editable strategy rules and CSV-based backtesting.
2. Add more indicators and a multi-symbol watchlist.
3. Add a broker sandbox/paper adapter where supported.
4. Only after validation, design a live adapter with explicit user opt-in and safeguards.
