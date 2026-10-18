import streamlit as st
import pandas as pd
from market_data import load_demo_data, load_yfinance_data, load_uploaded_csv
from trading_engine import add_indicators, latest_signal
from paper_broker import PaperBroker
from risk_manager import calculate_quantity

st.set_page_config(page_title="Indian Intraday AI Trader", page_icon="📈", layout="wide")
st.title("📈 Indian Intraday Trading Agent")
st.caption("Paper trading only • Rule-based signals • No real-money orders")
broker = PaperBroker()

with st.sidebar:
    st.header("Trading settings")
    source = st.selectbox("Market data source", ["Demo data", "Yahoo Finance (best-effort)", "Upload OHLCV CSV"])
    symbol = st.text_input("NSE symbol", "RELIANCE").strip().upper()
    interval = st.selectbox("Candle interval", ["5m", "15m", "30m", "1h"], index=0)
    period = st.selectbox("History", ["1d", "5d", "1mo"], index=1)
    capital = st.number_input("Paper account balance (₹)", min_value=1000.0, value=100000.0, step=5000.0)
    risk_pct = st.slider("Risk per trade (%)", min_value=0.1, max_value=2.0, value=0.5, step=0.1)
    max_trade_value = st.number_input("Max position value (₹)", min_value=1000.0, value=20000.0, step=1000.0)
    st.warning("Educational example only. Validate with backtesting before relying on signals.")

uploaded = None
if source == "Upload OHLCV CSV":
    uploaded = st.file_uploader("Upload candles CSV (timestamp, open, high, low, close; volume optional)", type=["csv"])

if st.button("Load data and scan", type="primary", use_container_width=True):
    try:
        if source == "Demo data":
            df, shown_symbol = load_demo_data(), "DEMO"
        elif source == "Yahoo Finance (best-effort)":
            df, shown_symbol = load_yfinance_data(symbol, interval, period), symbol
        else:
            if uploaded is None:
                st.error("Upload a CSV file first.")
                st.stop()
            df, shown_symbol = load_uploaded_csv(uploaded), (symbol or "UPLOAD")
        if df.empty or len(df) < 25:
            st.error("Not enough candle data. Load at least 25 rows.")
            st.stop()
        df = add_indicators(df)
        signal = latest_signal(df)
        last = df.iloc[-1]
        qty = calculate_quantity(capital, risk_pct, float(last["close"]), float(last["stop_loss"]), max_trade_value)
        st.session_state["scan_df"] = df
        st.session_state["scan_signal"] = signal
        st.session_state["scan_symbol"] = shown_symbol
        st.session_state["scan_qty"] = qty
    except Exception as exc:
        st.error(f"Could not scan data: {exc}")

if "scan_df" in st.session_state:
    df = st.session_state["scan_df"]
    signal = st.session_state["scan_signal"]
    shown_symbol = st.session_state["scan_symbol"]
    qty = st.session_state["scan_qty"]
    last = df.iloc[-1]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Symbol", shown_symbol)
    c2.metric("Last close", f"₹{float(last['close']):,.2f}")
    c3.metric("Signal", signal)
    c4.metric("Suggested quantity", f"{qty:,}")
    st.write("### Latest indicators")
    st.dataframe(df.tail(20), use_container_width=True)
    st.line_chart(df.set_index("timestamp")[["close", "ema_fast", "ema_slow"]].tail(100))
    st.caption("Starter rule: EMA 9/21 crossover with RSI confirmation. ATR stop is indicative, not a guarantee.")

    position = broker.get_open_position(shown_symbol)
    st.write("### Paper order controls")
    if position:
        st.info(f"Open paper position: {position['side']} {position['quantity']} shares at ₹{position['entry_price']:.2f}")
        if st.button("Close paper position at latest close"):
            broker.close_position(shown_symbol, float(last["close"]), "Manual paper close")
            st.success("Paper position closed.")
            st.rerun()
    elif signal in ("BUY", "SELL") and qty > 0:
        if st.button(f"Execute {signal} in paper account", type="primary"):
            broker.open_position(shown_symbol, signal, qty, float(last["close"]), float(last["stop_loss"] if signal == "BUY" else last["sell_stop"]))
            st.success(f"Paper {signal} recorded. No real order was sent.")
            st.rerun()
    else:
        st.info("No actionable signal or quantity is zero. No order has been placed.")

st.write("### Paper trading history")
history = broker.history()
if history.empty:
    st.info("No paper trades yet.")
else:
    st.dataframe(history, use_container_width=True)
    st.download_button("Download trade history CSV", history.to_csv(index=False), "paper_trades.csv", "text/csv")

st.write("### Before live trading")
st.markdown("Live trading is intentionally not implemented. A future broker adapter needs official broker APIs, secret storage, explicit opt-in, order validation, duplicate-order protection, and an emergency kill switch. Free hosting and free market data are not guaranteed to support unattended intraday execution.")
