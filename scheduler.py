import json
import os
import subprocess
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parent
PLAN_FILE = ROOT / "trade_plan.json"
STATE_FILE = ROOT / "paper_scheduler_state.json"
IST = ZoneInfo("Asia/Kolkata")


def read_json(path, default):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("encrypted"):
            key = os.environ.get("TRADING_AGENT_ENCRYPTION_KEY", "").strip()
            if not key:
                raise RuntimeError("TRADING_AGENT_ENCRYPTION_KEY is not configured.")
            return json.loads(Fernet(key.encode("utf-8")).decrypt(value["encrypted"].encode("ascii")).decode("utf-8"))
        return value
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, value):
    key = os.environ.get("TRADING_AGENT_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("TRADING_AGENT_ENCRYPTION_KEY is not configured; refusing to write unencrypted state.")
    encrypted = Fernet(key.encode("utf-8")).encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8")).decode("ascii")
    wrapper = {"encrypted": encrypted}
    path.write_text(json.dumps(wrapper, indent=2) + "\n", encoding="utf-8")


def current_quote(symbol):
    ticker = symbol if "." in symbol else f"{symbol}.NS"
    # Prefer the latest one-minute bar, with a short recent-history fallback.
    for period, interval in (("1d", "1m"), ("5d", "5m")):
        try:
            data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
            if not data.empty and "Close" in data:
                closes = pd.to_numeric(data["Close"], errors="coerce").dropna()
                if not closes.empty and float(closes.iloc[-1]) > 0:
                    return float(closes.iloc[-1])
        except Exception:
            pass
    return None


def plan_key(plan):
    fields = ("symbol", "buy_price", "quantity", "trade_date", "buy_time", "sell_time")
    return "|".join(str(plan.get(k, "")) for k in fields)


def main():
    now = datetime.now(IST)
    plan = read_json(PLAN_FILE, None)
    state = read_json(STATE_FILE, {})
    if not isinstance(plan, dict) or not plan.get("symbol"):
        print("No shared trade plan found; nothing to do.")
        return

    trade_date = str(plan.get("trade_date", ""))
    if trade_date != now.date().isoformat():
        print(f"Plan date {trade_date} does not match today {now.date()}; nothing to do.")
        return

    symbol = str(plan["symbol"]).strip().upper()
    qty = int(plan["quantity"])
    limit_price = float(plan["buy_price"])
    buy_time = time.fromisoformat(str(plan["buy_time"]))
    sell_time = time.fromisoformat(str(plan["sell_time"]))
    key = plan_key(plan)

    if state.get("plan_key") != key:
        state = {
            "plan_key": key, "trade_date": trade_date, "symbol": symbol,
            "quantity": qty, "buy_limit_price": limit_price,
            "status": "WAITING_FOR_BUY", "updated_at_ist": now.isoformat(),
            "events": []
        }

    status = state.get("status")
    current_time = now.time().replace(tzinfo=None)

    if status in ("SOLD", "BUY_NOT_FILLED"):
        print(f"Plan already finished with state {status}.")
        return

    if status == "WAITING_FOR_BUY" and current_time >= buy_time:
        if current_time >= sell_time:
            state["status"] = "BUY_NOT_FILLED"
            state["message"] = "Buy limit was not filled before the planned sell time."
            state["updated_at_ist"] = now.isoformat()
            write_json(STATE_FILE, state)
            print(state["message"])
            return

        quote = current_quote(symbol)
        if quote is None:
            print("No current quote available; will retry on the next scheduled run.")
            return
        if quote > limit_price:
            print(
                f"Buy not filled: latest quote ₹{quote:.2f} is above the "
                f"₹{limit_price:.2f} buy limit; will retry until sell time."
            )
            return

        state.update({
            "status": "BOUGHT", "buy_fill_price": round(quote, 2),
            "buy_fill_quantity": qty, "buy_filled_at_ist": now.isoformat(),
            "message": "Simulated buy filled at the latest available quote."
        })
        state["events"].append({
            "event": "BUY_FILLED", "price": round(quote, 2), "quantity": qty,
            "time_ist": now.isoformat()
        })
        state["updated_at_ist"] = now.isoformat()
        write_json(STATE_FILE, state)
        print(state["message"])
        return

    if status == "BOUGHT" and current_time >= sell_time:
        quote = current_quote(symbol)
        if quote is None:
            state["message"] = "Buy succeeded but no sell quote is available; sell will be retried."
            state["updated_at_ist"] = now.isoformat()
            write_json(STATE_FILE, state)
            print(state["message"])
            return
        entry = float(state["buy_fill_price"])
        filled_qty = int(state["buy_fill_quantity"])
        exit_price = round(quote, 2)
        pnl = round((exit_price - entry) * filled_qty, 2)
        invested = entry * filled_qty
        state.update({
            "status": "SOLD", "sell_fill_price": exit_price,
            "sell_fill_quantity": filled_qty, "sell_filled_at_ist": now.isoformat(),
            "buy_value": round(invested, 2), "sell_value": round(exit_price * filled_qty, 2),
            "gross_pnl": pnl, "return_pct": round(pnl / invested * 100, 4) if invested else 0.0,
            "message": "Simulated sell completed for the same stock and filled quantity."
        })
        state["events"].append({
            "event": "SELL_FILLED", "price": exit_price, "quantity": filled_qty,
            "time_ist": now.isoformat(), "gross_pnl": pnl
        })
        state["updated_at_ist"] = now.isoformat()
        write_json(STATE_FILE, state)
        print(state["message"])
        return

    print(f"Nothing due now. Current state: {state.get('status', 'UNKNOWN')}")


if __name__ == "__main__":
    main()
