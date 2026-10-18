import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


# ------------------------- Market data -------------------------
def normalize_columns(df):
    data = df.copy()
    data.columns = [str(c).strip().lower().replace(" ", "_") for c in data.columns]
    aliases = {"datetime": "timestamp", "date": "timestamp", "adj_close": "close"}
    data = data.rename(columns={c: aliases.get(c, c) for c in data.columns})
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(data.columns):
        raise ValueError("CSV needs timestamp/date, open, high, low, close columns")
    data["timestamp"] = pd.to_datetime(data["timestamp"], errors="coerce")
    for col in ["open", "high", "low", "close"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["timestamp", "open", "high", "low", "close"])
    if "volume" not in data.columns:
        data["volume"] = 0
    return data.sort_values("timestamp").reset_index(drop=True)


def load_uploaded_csv(file):
    return normalize_columns(pd.read_csv(file))


def load_yfinance_data(symbol, interval="5m", period="5d"):
    import yfinance as yf

    ticker = symbol if "." in symbol else f"{symbol}.NS"
    raw = yf.download(
        ticker, interval=interval, period=period,
        auto_adjust=False, progress=False
    )
    if raw.empty:
        raise ValueError(
            "No data returned. Check the symbol/interval or upload a CSV. "
            "Yahoo intraday history may be limited."
        )
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    time_col = "datetime" if "datetime" in raw.columns else "date"
    raw = raw.rename(columns={time_col: "timestamp"})
    return normalize_columns(raw)



def get_previous_close(symbol: str) -> float:
    """Return the latest available completed daily close for an NSE symbol."""
    import yfinance as yf

    clean_symbol = str(symbol).strip().upper()
    if not clean_symbol:
        raise ValueError("Enter an NSE stock symbol.")
    ticker = clean_symbol if "." in clean_symbol else f"{clean_symbol}.NS"
    hist = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
    if hist.empty or "Close" not in hist.columns:
        raise ValueError(
            f"Could not fetch the previous close for {clean_symbol}. "
            "Check the NSE symbol or try again when market data is available."
        )
    closes = pd.to_numeric(hist["Close"], errors="coerce").dropna()
    if closes.empty or float(closes.iloc[-1]) <= 0:
        raise ValueError(f"No valid previous closing price found for {clean_symbol}.")
    return float(closes.iloc[-1])


def calculate_planned_buy_price(previous_close: float) -> float:
    """Add 1.99% to the previous close and round to paise."""
    return round(float(previous_close) * 1.0199 + 1e-9, 2)

def load_demo_data():
    rng = np.random.default_rng(7)
    n = 180
    timestamps = pd.date_range(
        end=pd.Timestamp.now().floor("5min"), periods=n, freq="5min"
    )
    noise = rng.normal(0.02, 0.6, n)
    close = 2450 + np.cumsum(noise) + np.sin(np.arange(n) / 12) * 3
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.2, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.2, n)
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.integers(100, 10000, n),
    })


# ------------------------- Trading indicators -------------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy().sort_values("timestamp").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    data["ema_fast"] = data["close"].ewm(span=9, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=21, adjust=False).mean()
    delta = data["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    data["rsi"] = (100 - (100 / (1 + rs))).fillna(50)
    previous_close = data["close"].shift(1)
    tr = pd.concat([
        data["high"] - data["low"],
        (data["high"] - previous_close).abs(),
        (data["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    data["atr"] = tr.rolling(14, min_periods=1).mean()
    data["stop_loss"] = data["close"] - (1.5 * data["atr"])
    data["sell_stop"] = data["close"] + (1.5 * data["atr"])
    return data


def latest_signal(df: pd.DataFrame) -> str:
    if len(df) < 22:
        return "WAIT"
    prev, last = df.iloc[-2], df.iloc[-1]
    crossed_up = (
        prev["ema_fast"] <= prev["ema_slow"]
        and last["ema_fast"] > last["ema_slow"]
    )
    crossed_down = (
        prev["ema_fast"] >= prev["ema_slow"]
        and last["ema_fast"] < last["ema_slow"]
    )
    if crossed_up and 50 <= last["rsi"] <= 70:
        return "BUY"
    if crossed_down and 30 <= last["rsi"] <= 50:
        return "SELL"
    return "WAIT"


# ------------------------- Risk management -------------------------
def calculate_quantity(capital, risk_pct, entry, stop, max_position_value):
    capital, entry, stop = float(capital), float(entry), float(stop)
    if capital <= 0 or entry <= 0 or float(max_position_value) <= 0:
        return 0
    risk_amount = capital * (float(risk_pct) / 100.0)
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0:
        return 0
    qty_by_risk = int(risk_amount / risk_per_share)
    qty_by_value = int(float(max_position_value) / entry)
    return max(0, min(qty_by_risk, qty_by_value))


# ------------------------- Paper trading broker -------------------------
DB_PATH = Path("paper_trades.db")


class PaperBroker:
    def __init__(self, db_path=DB_PATH):
        self.db_path = str(db_path)
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    exit_price REAL,
                    pnl REAL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS saved_paper_plan (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    symbol TEXT NOT NULL,
                    buy_price REAL NOT NULL,
                    quantity INTEGER NOT NULL,
                    trade_date TEXT NOT NULL,
                    buy_time TEXT NOT NULL,
                    sell_time TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def open_position(self, symbol, side, quantity, entry_price, stop_loss):
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL")
        if int(quantity) <= 0 or float(entry_price) <= 0:
            raise ValueError("Quantity and price must be positive")
        if self.get_open_position(symbol):
            raise ValueError("This symbol already has an open paper position")
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO trades(symbol, side, quantity, entry_price, stop_loss, "
                "status, reason) VALUES(?,?,?,?,?,'OPEN','Signal confirmed by user')",
                (symbol, side, int(quantity), float(entry_price), float(stop_loss)),
            )

    def get_open_position(self, symbol):
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM trades WHERE symbol=? AND status='OPEN' "
                "ORDER BY id DESC LIMIT 1", (symbol,)
            ).fetchone()
            return dict(row) if row else None

    def close_position(self, symbol, exit_price, reason="Closed"):
        position = self.get_open_position(symbol)
        if not position:
            raise ValueError("No open paper position for this symbol")
        multiplier = 1 if position["side"] == "BUY" else -1
        pnl = (
            (float(exit_price) - position["entry_price"])
            * position["quantity"] * multiplier
        )
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "UPDATE trades SET exit_price=?, pnl=?, status='CLOSED', "
                "reason=?, closed_at=CURRENT_TIMESTAMP WHERE id=?",
                (float(exit_price), pnl, reason, position["id"]),
            )

    def history(self):
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql_query(
                "SELECT * FROM trades ORDER BY id DESC", con
            )

    def save_plan(self, symbol, buy_price, quantity, trade_date, buy_time, sell_time):
        symbol = str(symbol).strip().upper()
        buy_price = float(buy_price)
        quantity = int(quantity)
        if not symbol:
            raise ValueError("Enter a stock symbol.")
        if buy_price <= 0 or quantity <= 0:
            raise ValueError("Buy price and quantity must be positive.")
        if sell_time <= buy_time:
            raise ValueError("Sell time must be later than buy time.")
        with sqlite3.connect(self.db_path) as con:
            con.execute("""
                INSERT INTO saved_paper_plan
                    (id, symbol, buy_price, quantity, trade_date, buy_time, sell_time, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    symbol=excluded.symbol,
                    buy_price=excluded.buy_price,
                    quantity=excluded.quantity,
                    trade_date=excluded.trade_date,
                    buy_time=excluded.buy_time,
                    sell_time=excluded.sell_time,
                    updated_at=CURRENT_TIMESTAMP
            """, (symbol, buy_price, quantity, str(trade_date), str(buy_time), str(sell_time)))

    def get_saved_plan(self):
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM saved_paper_plan WHERE id=1").fetchone()
            return dict(row) if row else None

    def delete_saved_plan(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM saved_paper_plan WHERE id=1")


# ------------------------- Streamlit interface -------------------------
st.set_page_config(
    page_title="Indian Intraday AI Trader",
    page_icon="📈",
    layout="wide",
)
st.title("📈 Indian Intraday Trading Agent")
st.caption("Paper trading only • Saved overnight plans • Rule-based signals • No real-money orders")
st.info(
    "This app is for educational paper trading. Yahoo Finance data is best-effort "
    "and may be delayed, incomplete, or unavailable. No live broker orders are sent."
)

broker = PaperBroker()

# Saved overnight plan is stored in the same SQLite database as paper trades.
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
saved_plan = broker.get_saved_plan()

st.write("### 🌙 Overnight paper-trade plan")
st.caption(
    "Enter the NSE stock symbol and quantity. The app fetches the latest available "
    "completed daily close and calculates the planned buy price as previous close + 1.99%. "
    "This saves a paper plan only; it does not schedule or send orders."
)
with st.form("overnight_plan_form"):
    plan_col1, plan_col2 = st.columns(2)
    plan_symbol = plan_col1.text_input(
        "NSE stock symbol",
        value=(saved_plan["symbol"] if saved_plan else ""),
        placeholder="e.g. RELIANCE",
        key="overnight_symbol",
    ).strip().upper()
    plan_quantity = plan_col2.number_input(
        "Quantity (shares)",
        min_value=1,
        value=int(saved_plan["quantity"]) if saved_plan else 1,
        step=1,
        key="overnight_quantity",
    )
    default_date = (
        date.fromisoformat(saved_plan["trade_date"])
        if saved_plan else (datetime.now(IST).date() + timedelta(days=1))
    )
    plan_date = st.date_input("Planned trading date", value=default_date, key="overnight_date")
    plan_time_col1, plan_time_col2 = st.columns(2)
    saved_buy_time = time.fromisoformat(saved_plan["buy_time"]) if saved_plan else time(9, 0)
    saved_sell_time = time.fromisoformat(saved_plan["sell_time"]) if saved_plan else time(9, 15)
    plan_buy_time = plan_time_col1.time_input("Simulated buy time (IST)", value=saved_buy_time, key="overnight_buy_time")
    plan_sell_time = plan_time_col2.time_input("Simulated sell time (IST)", value=saved_sell_time, key="overnight_sell_time")
    plan_buttons = st.columns(2)
    save_plan_clicked = plan_buttons[0].form_submit_button("Fetch close & save plan", type="primary", use_container_width=True)
    clear_plan_clicked = plan_buttons[1].form_submit_button("Clear saved plan", use_container_width=True)

if save_plan_clicked:
    try:
        if not plan_symbol:
            raise ValueError("Enter an NSE stock symbol.")
        if plan_sell_time <= plan_buy_time:
            raise ValueError("Sell time must be later than buy time.")
        previous_close = get_previous_close(plan_symbol)
        calculated_buy_price = calculate_planned_buy_price(previous_close)
        broker.save_plan(
            plan_symbol, calculated_buy_price, plan_quantity,
            plan_date, plan_buy_time, plan_sell_time
        )
        st.success(
            f"Saved paper plan for {plan_symbol}. Previous close: ₹{previous_close:.2f}; "
            f"planned buy price (+1.99%): ₹{calculated_buy_price:.2f}."
        )
        st.rerun()
    except Exception as exc:
        st.error(f"Could not fetch price or save plan: {exc}")

if clear_plan_clicked:
    broker.delete_saved_plan()
    st.success("Saved paper-trading plan cleared.")
    st.rerun()

saved_plan = broker.get_saved_plan()
if saved_plan:
    calculated_buy = float(saved_plan["buy_price"])
    target_price = round(calculated_buy * 1.01 + 1e-9, 2)
    previous_close_estimate = round(calculated_buy / 1.0199, 2)
    plan_summary = pd.DataFrame([{
        "Symbol": saved_plan["symbol"],
        "Previous close (₹)": previous_close_estimate,
        "Planned buy (+1.99%) (₹)": calculated_buy,
        "Quantity": saved_plan["quantity"],
        "Illustrative +1% sell target (₹)": target_price,
        "Trade date": saved_plan["trade_date"],
        "Buy time (IST)": saved_plan["buy_time"],
        "Sell time (IST)": saved_plan["sell_time"],
        "Last saved": saved_plan["updated_at"],
    }])
    st.dataframe(plan_summary, hide_index=True, use_container_width=True)
    st.warning(
        "The previous close shown is reconstructed from the saved buy price and may differ "
        "by a few paise because of rounding. The market-data close is fetched when you save "
        "the plan, not refreshed automatically at execution time. This is still a saved paper "
        "plan, not an active scheduler; no orders are automatically placed."
    )

with st.sidebar:
    st.header("Trading settings")
    source = st.selectbox(
        "Market data source",
        ["Demo data", "Yahoo Finance (best-effort)", "Upload OHLCV CSV"],
    )
    symbol = st.text_input("NSE symbol", "RELIANCE").strip().upper()
    interval = st.selectbox("Candle interval", ["5m", "15m", "30m", "1h"], index=0)
    period = st.selectbox("History", ["1d", "5d", "1mo"], index=1)
    capital = st.number_input(
        "Paper account balance (₹)", min_value=1000.0,
        value=100000.0, step=5000.0,
    )
    risk_pct = st.slider(
        "Risk per trade (%)", min_value=0.1, max_value=2.0,
        value=0.5, step=0.1,
    )
    max_trade_value = st.number_input(
        "Max position value (₹)", min_value=1000.0,
        value=20000.0, step=1000.0,
    )

uploaded = None
if source == "Upload OHLCV CSV":
    uploaded = st.file_uploader(
        "Upload candles CSV (timestamp, open, high, low, close; volume optional)",
        type=["csv"],
    )

if st.button("Load data and scan", type="primary", use_container_width=True):
    try:
        if source == "Demo data":
            df, shown_symbol = load_demo_data(), "DEMO"
        elif source == "Yahoo Finance (best-effort)":
            if not symbol:
                st.error("Enter an NSE symbol first.")
                st.stop()
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
        qty = calculate_quantity(
            capital, risk_pct, float(last["close"]),
            float(last["stop_loss"]), max_trade_value,
        )
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
    st.caption(
        "Starter rule: EMA 9/21 crossover with RSI confirmation. "
        "ATR stop is indicative, not a guarantee."
    )

    position = broker.get_open_position(shown_symbol)
    st.write("### Paper order controls")
    if position:
        st.info(
            f"Open paper position: {position['side']} {position['quantity']} "
            f"shares at ₹{position['entry_price']:.2f}"
        )
        if st.button("Close paper position at latest close"):
            broker.close_position(
                shown_symbol, float(last["close"]), "Manual paper close"
            )
            st.success("Paper position closed.")
            st.rerun()
    elif signal in ("BUY", "SELL") and qty > 0:
        if st.button(f"Execute {signal} in paper account", type="primary"):
            stop = float(last["stop_loss"] if signal == "BUY" else last["sell_stop"])
            broker.open_position(
                shown_symbol, signal, qty, float(last["close"]), stop
            )
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
    st.download_button(
        "Download trade history CSV",
        history.to_csv(index=False),
        "paper_trades.csv",
        "text/csv",
    )

st.write("### Before live trading")
st.markdown(
    "Live trading is intentionally not implemented. A future broker adapter needs "
    "official broker APIs, secret storage, explicit opt-in, order validation, "
    "duplicate-order protection, and an emergency kill switch. Free hosting and "
    "free market data are not guaranteed to support unattended intraday execution. "
    "The saved plan and paper-trade history live in local SQLite. They persist only while the host preserves the paper_trades.db file; some free hosts can reset local files, so download/keep a backup if the host is ephemeral. Saved plans do not auto-execute."
)
