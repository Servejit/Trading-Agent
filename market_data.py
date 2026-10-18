import numpy as np
import pandas as pd

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
    raw = yf.download(ticker, interval=interval, period=period, auto_adjust=False, progress=False)
    if raw.empty:
        raise ValueError("No data returned. Check symbol/interval or use CSV. Intraday history may be limited.")
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw = raw.reset_index()
    raw.columns = [str(c).strip().lower().replace(" ", "_") for c in raw.columns]
    time_col = "datetime" if "datetime" in raw.columns else "date"
    raw = raw.rename(columns={time_col: "timestamp"})
    return normalize_columns(raw)

def load_demo_data():
    rng = np.random.default_rng(7)
    n = 180
    timestamps = pd.date_range(end=pd.Timestamp.now().floor("5min"), periods=n, freq="5min")
    noise = rng.normal(0.02, 0.6, n)
    close = 2450 + np.cumsum(noise) + np.sin(np.arange(n) / 12) * 3
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + rng.uniform(0.1, 1.2, n)
    low = np.minimum(open_, close) - rng.uniform(0.1, 1.2, n)
    return pd.DataFrame({"timestamp": timestamps, "open": open_, "high": high, "low": low, "close": close, "volume": rng.integers(100, 10000, n)})
