import pandas as pd

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy().sort_values("timestamp").reset_index(drop=True)
    for col in ["open", "high", "low", "close"]:
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    data["ema_fast"] = data["close"].ewm(span=9, adjust=False).mean()
    data["ema_slow"] = data["close"].ewm(span=21, adjust=False).mean()
    delta = data["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    data["rsi"] = (100 - (100 / (1 + rs))).fillna(50)
    previous_close = data["close"].shift(1)
    tr = pd.concat([data["high"] - data["low"], (data["high"] - previous_close).abs(), (data["low"] - previous_close).abs()], axis=1).max(axis=1)
    data["atr"] = tr.rolling(14, min_periods=1).mean()
    data["stop_loss"] = data["close"] - (1.5 * data["atr"])
    data["sell_stop"] = data["close"] + (1.5 * data["atr"])
    return data

def latest_signal(df: pd.DataFrame) -> str:
    if len(df) < 22:
        return "WAIT"
    prev, last = df.iloc[-2], df.iloc[-1]
    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]
    if crossed_up and 50 <= last["rsi"] <= 70:
        return "BUY"
    if crossed_down and 30 <= last["rsi"] <= 50:
        return "SELL"
    return "WAIT"
