import base64
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from cryptography.fernet import Fernet

st.set_page_config(page_title="Northstar | Paper Trading", page_icon="◈", layout="wide", initial_sidebar_state="collapsed")
IST = ZoneInfo("Asia/Kolkata")
DB_PATH = Path("paper_trades.db")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@400;500;600;700;800&display=swap');
.stApp{background:radial-gradient(ellipse at 10% 0%,rgba(72,101,180,.2),transparent 36%),#080e1a;color:#edf2ff;font-family:'DM Sans',sans-serif}
.block-container{max-width:1220px;padding-top:1.8rem;padding-bottom:3rem}
h1,h2,h3{font-family:'Manrope',sans-serif!important;letter-spacing:-.035em;color:#f4f7ff}
h1{font-weight:800!important}
p,label{color:#b5c0d8}
div[data-testid="stMetric"]{background:linear-gradient(145deg,rgba(22,33,55,.96),rgba(14,23,39,.96));border:1px solid rgba(155,177,218,.16);border-radius:16px;padding:17px;min-height:108px}
div[data-testid="stMetricLabel"]{color:#a6b5d2!important;font-size:.84rem!important}
div[data-testid="stMetricValue"]{color:#f4f7ff!important;font-family:'Manrope',sans-serif;font-weight:800}
div[data-testid="stForm"],div[data-testid="stExpander"]{background:rgba(17,26,44,.74);border:1px solid rgba(155,177,218,.16);border-radius:18px;padding:16px}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:11px;min-height:43px;font-weight:700;border:1px solid rgba(141,168,255,.3)}
.stButton>button[kind="primary"],.stFormSubmitButton>button[kind="primary"]{background:linear-gradient(110deg,#6e8df5,#8b79ed);color:white;border:0}
hr{border-color:rgba(155,177,218,.16)}
div[data-testid="stDataFrame"]{border:1px solid rgba(155,177,218,.16);border-radius:12px;overflow:hidden}
.eyebrow{text-transform:uppercase;letter-spacing:.16em;color:#8fa8ff;font-size:.73rem;font-weight:800}
.hero{padding:25px 27px;border:1px solid rgba(155,177,218,.16);border-radius:22px;background:linear-gradient(115deg,rgba(24,38,65,.94),rgba(15,24,41,.88));margin-bottom:20px}
.pill{display:inline-block;border:1px solid rgba(141,168,255,.3);color:#c3ceff;border-radius:999px;padding:5px 10px;font-size:.76rem;font-weight:700}
</style>
""", unsafe_allow_html=True)

def money(v):
    return f"₹{float(v):,.2f}"

def get_previous_close(symbol):
    import yfinance as yf
    symbol = str(symbol).strip().upper()
    if not symbol:
        raise ValueError("Enter an NSE stock symbol.")
    ticker = symbol if "." in symbol else f"{symbol}.NS"
    hist = yf.Ticker(ticker).history(period="15d", interval="1d", auto_adjust=False)
    if hist.empty or "Close" not in hist:
        raise ValueError("No price data found. Check the NSE symbol and try again.")
    today = datetime.now(IST).date()
    data = pd.DataFrame({"day": pd.to_datetime(hist.index).date, "close": pd.to_numeric(hist["Close"], errors="coerce").values})
    data = data[(data.day < today) & data.close.notna() & (data.close > 0)]
    if data.empty:
        raise ValueError("No completed daily close before today was found.")
    return float(data.iloc[-1].close)

def buy_price_from_close(previous_close):
    return round(float(previous_close) * 1.0199 + 1e-9, 2)


def sync_plan_to_github(plan):
    """Mirror the saved plan to the repository for the scheduled runner."""
    token = os.environ.get("TRADING_AGENT_GITHUB_TOKEN", "").strip()
    encryption_key = os.environ.get("TRADING_AGENT_ENCRYPTION_KEY", "").strip()
    if not token:
        return False, "Add the TRADING_AGENT_GITHUB_TOKEN Codespaces secret to enable background plan syncing."
    if not encryption_key:
        return False, "Add TRADING_AGENT_ENCRYPTION_KEY in Codespaces and GitHub Actions secrets to encrypt the shared plan."
    api_url = "https://api.github.com/repos/Servejit/Trading-Agent/contents/trade_plan.json"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "Northstar-Paper-Trading-App"}
    try:
        request = urllib.request.Request(api_url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                existing = json.loads(response.read().decode("utf-8"))
            sha = existing.get("sha")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                sha = None
            else:
                raise
        payload = {
            "symbol": str(plan.get("symbol", "")).strip().upper() if plan else "",
            "buy_price": float(plan.get("buy_price", 0)) if plan else 0,
            "quantity": int(plan.get("quantity", 0)) if plan else 0,
            "trade_date": str(plan.get("trade_date", "")) if plan else "",
            "buy_time": str(plan.get("buy_time", "09:00:00")) if plan else "09:00:00",
            "sell_time": str(plan.get("sell_time", "09:15:00")) if plan else "09:15:00",
        }
        encrypted_payload = Fernet(encryption_key.encode("utf-8")).encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")
        encoded = base64.b64encode((json.dumps({"encrypted": encrypted_payload}, indent=2) + "\n").encode("utf-8")).decode("ascii")
        body = {"message": "Sync saved paper-trade plan from Northstar app", "content": encoded}
        if sha:
            body["sha"] = sha
        request = urllib.request.Request(api_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="PUT")
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True, "Plan synced to GitHub for the scheduled paper runner."
    except Exception as exc:
        return False, f"Plan saved locally, but GitHub sync failed: {exc}"


def load_remote_scheduler_state():
    url = "https://raw.githubusercontent.com/Servejit/Trading-Agent/main/paper_scheduler_state.json"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Northstar-Paper-Trading-App"})
        with urllib.request.urlopen(request, timeout=5) as response:
            wrapper = json.loads(response.read().decode("utf-8"))
        if isinstance(wrapper, dict) and wrapper.get("encrypted"):
            key = os.environ.get("TRADING_AGENT_ENCRYPTION_KEY", "").strip()
            if not key:
                return {}
            value = json.loads(Fernet(key.encode("utf-8")).decrypt(wrapper["encrypted"].encode("ascii")).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        return wrapper if isinstance(wrapper, dict) else {}
    except Exception:
        return {}

class PaperBroker:
    def __init__(self):
        with sqlite3.connect(DB_PATH) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS trades(
                id INTEGER PRIMARY KEY AUTOINCREMENT,symbol TEXT NOT NULL,side TEXT NOT NULL,
                quantity INTEGER NOT NULL,entry_price REAL NOT NULL,stop_loss REAL,
                exit_price REAL,pnl REAL,status TEXT NOT NULL,reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,closed_at TEXT)""")
            con.execute("""CREATE TABLE IF NOT EXISTS saved_paper_plan(
                id INTEGER PRIMARY KEY CHECK(id=1),symbol TEXT NOT NULL,buy_price REAL NOT NULL,
                quantity INTEGER NOT NULL,trade_date TEXT NOT NULL,buy_time TEXT NOT NULL,
                sell_time TEXT NOT NULL,updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    def plan(self):
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory=sqlite3.Row
            row=con.execute("SELECT * FROM saved_paper_plan WHERE id=1").fetchone()
            return dict(row) if row else None
    def save_plan(self,symbol,price,qty,day,buy_time,sell_time):
        symbol=str(symbol).strip().upper()
        if not symbol or float(price)<=0 or int(qty)<=0: raise ValueError("Enter a valid symbol, price and quantity.")
        if sell_time<=buy_time: raise ValueError("Sell time must be later than buy time.")
        with sqlite3.connect(DB_PATH) as con:
            con.execute("""INSERT INTO saved_paper_plan(id,symbol,buy_price,quantity,trade_date,buy_time,sell_time,updated_at)
            VALUES(1,?,?,?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(id) DO UPDATE SET
            symbol=excluded.symbol,buy_price=excluded.buy_price,quantity=excluded.quantity,
            trade_date=excluded.trade_date,buy_time=excluded.buy_time,sell_time=excluded.sell_time,
            updated_at=CURRENT_TIMESTAMP""",(symbol,float(price),int(qty),str(day),str(buy_time),str(sell_time)))
    def clear_plan(self):
        with sqlite3.connect(DB_PATH) as con: con.execute("DELETE FROM saved_paper_plan WHERE id=1")
    def open_trade(self,symbol):
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory=sqlite3.Row
            row=con.execute("SELECT * FROM trades WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1",(symbol,)).fetchone()
            return dict(row) if row else None
    def buy(self,plan):
        with sqlite3.connect(DB_PATH) as con:
            if con.execute("SELECT id FROM trades WHERE symbol=? AND status='OPEN' LIMIT 1",(plan["symbol"],)).fetchone():
                raise ValueError("This stock already has an open paper position.")
            con.execute("INSERT INTO trades(symbol,side,quantity,entry_price,status,reason) VALUES(?,'BUY',?,?,'OPEN','Simulated buy from saved plan')",(plan["symbol"],int(plan["quantity"]),float(plan["buy_price"])))
    def sell(self,trade_id,price):
        if float(price)<=0: raise ValueError("Sell price must be positive.")
        with sqlite3.connect(DB_PATH) as con:
            con.row_factory=sqlite3.Row
            row=con.execute("SELECT * FROM trades WHERE id=? AND status='OPEN'",(int(trade_id),)).fetchone()
            if not row: raise ValueError("No open paper trade found.")
            t=dict(row); qty=int(t["quantity"]); entry=float(t["entry_price"]); exit_price=float(price)
            pnl=(exit_price-entry)*qty; invested=entry*qty
            con.execute("UPDATE trades SET exit_price=?,pnl=?,status='CLOSED',reason='Paper sell recorded',closed_at=CURRENT_TIMESTAMP WHERE id=?",(exit_price,pnl,int(trade_id)))
            return {"symbol":t["symbol"],"quantity":qty,"buy_price":entry,"sell_price":exit_price,"buy_value":invested,"sell_value":exit_price*qty,"pnl":pnl,"return_pct":pnl/invested*100 if invested else 0}
    def history(self):
        with sqlite3.connect(DB_PATH) as con: return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC",con)

broker=PaperBroker()
plan=broker.plan()
history=broker.history()
closed=history[history.status=="CLOSED"] if not history.empty else pd.DataFrame()
opened=history[history.status=="OPEN"] if not history.empty else pd.DataFrame()
total_pnl=float(pd.to_numeric(closed.pnl,errors="coerce").fillna(0).sum()) if not closed.empty else 0
wins=int((pd.to_numeric(closed.pnl,errors="coerce")>0).sum()) if not closed.empty else 0

st.markdown("""<div class="hero">
<div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
<div style="font-size:35px;background:linear-gradient(140deg,#7596ff,#a18aff);border-radius:13px;padding:3px 12px;color:white">◈</div>
<div><div class="eyebrow">NORTHSTAR · TRADING DESK</div><div style="font-family:Manrope,sans-serif;font-weight:800;font-size:1.8rem;color:#f4f7ff">Paper Trading Studio</div></div>
<div style="margin-left:auto"><span class="pill">PAPER MODE · NO LIVE ORDERS</span></div></div>
<p style="margin:16px 0 0;color:#a9b7d2">A focused workspace for your NSE plan, simulated buy and sell, and profit tracking — no indicators, no signals, no clutter.</p>
</div>""",unsafe_allow_html=True)
now=datetime.now(IST)
st.caption(f"India Standard Time · {now.strftime('%d %b %Y, %I:%M %p')} · Market data is best-effort")
a,b,c,d=st.columns(4)
a.metric("Realized P&L",money(total_pnl))
b.metric("Closed trades",len(closed))
c.metric("Winning trades",wins)
d.metric("Open positions",len(opened))
st.divider()

st.markdown('<div class="eyebrow">01 · PLAN</div>',unsafe_allow_html=True)
st.header("Overnight trade plan")
st.write("Enter a stock symbol and quantity. The app fetches the latest completed daily close and adds 1.99% to calculate the planned buy price.")
with st.form("plan_form"):
    l,r=st.columns([1.15,.85],gap="large")
    with l:
        sym=st.text_input("NSE stock symbol",value=plan["symbol"] if plan else "",placeholder="e.g. RELIANCE")
        qty=st.number_input("Quantity (shares)",min_value=1,max_value=10000000,value=int(plan["quantity"]) if plan else 1,step=1)
    with r:
        day_default=date.fromisoformat(plan["trade_date"]) if plan else now.date()+timedelta(days=1)
        trade_day=st.date_input("Trading date",value=day_default)
        bt=time.fromisoformat(plan["buy_time"]) if plan else time(9,0)
        stt=time.fromisoformat(plan["sell_time"]) if plan else time(9,15)
        t1,t2=st.columns(2)
        buy_t=t1.time_input("Buy time (IST)",value=bt)
        sell_t=t2.time_input("Sell time (IST)",value=stt)
    save=st.form_submit_button("Fetch previous close & save plan",type="primary",use_container_width=True)
if save:
    try:
        if sell_t<=buy_t: raise ValueError("Sell time must be later than buy time.")
        prev=get_previous_close(sym)
        bp=buy_price_from_close(prev)
        broker.save_plan(sym,bp,qty,trade_day,buy_t,sell_t)
        sync_ok, sync_message = sync_plan_to_github(broker.plan())
        st.session_state["plan_sync_status"] = {"ok": sync_ok, "message": sync_message}
        st.session_state["plan_calc"]={"symbol":sym.strip().upper(),"close":prev,"buy":bp}
        st.rerun()
    except Exception as e: st.error(f"Could not save plan: {e}")
if "plan_calc" in st.session_state:
    x=st.session_state["plan_calc"]
    st.success(f"{x['symbol']} · Previous close {money(x['close'])} · Planned buy {money(x['buy'])} (+1.99%).")
plan=broker.plan()
if plan:
    p1,p2,p3,p4=st.columns(4)
    p1.metric("Stock",plan["symbol"])
    p2.metric("Planned buy",money(plan["buy_price"]),"+1.99% vs previous close")
    p3.metric("Quantity",f"{int(plan['quantity']):,}")
    p4.metric("Illustrative +1% target",money(round(float(plan["buy_price"])*1.01+1e-9,2)))
    st.caption(f"Plan: {plan['trade_date']} · Buy {plan['buy_time']} IST · Sell {plan['sell_time']} IST · Saved {plan['updated_at']}")
    if st.button("Clear saved plan"):
        broker.clear_plan()
        sync_plan_to_github(None)
        st.rerun()
else: st.info("No saved plan yet. Fetch the previous close to create one.")

if "plan_sync_status" in st.session_state:
    sync_status = st.session_state["plan_sync_status"]
    if sync_status["ok"]:
        st.success(sync_status["message"])
    else:
        st.warning(sync_status["message"])
st.warning("The saved times are planning details only. This app does not run a background scheduler or automatically place orders.")
st.divider()

st.markdown('<div class="eyebrow">02 · PAPER EXECUTION</div>',unsafe_allow_html=True)
st.header("Simulated buy & sell")
st.write("Record simulated fills manually. A sell closes the same stock and exact quantity as the recorded paper buy.")
buy_col,sell_col=st.columns(2,gap="large")
with buy_col:
    st.subheader("Buy")
    if plan:
        st.write(f"**{plan['symbol']}** · {int(plan['quantity']):,} shares · **{money(plan['buy_price'])}**")
        if st.button("Record simulated buy",type="primary",use_container_width=True):
            try: broker.buy(plan); st.success("Paper buy recorded."); st.rerun()
            except Exception as e: st.error(str(e))
    else: st.caption("Save a plan first to enable simulated buy.")
with sell_col:
    st.subheader("Sell")
    trade=broker.open_trade(plan["symbol"]) if plan else None
    if trade:
        target=round(float(trade["entry_price"])*1.01+1e-9,2)
        st.write(f"**{trade['symbol']}** · {int(trade['quantity']):,} shares")
        st.write(f"Recorded buy price: **{money(trade['entry_price'])}**")
        price=st.number_input("Simulated sell fill price (₹)",min_value=.01,value=float(target),step=.05,format="%.2f",key=f"sell_{trade['id']}")
        st.caption("Default is an illustrative +1% target. Change it to the sell price you want to record.")
        if st.button("Record sell & calculate profit",type="primary",use_container_width=True):
            try: st.session_state["closed_summary"]=broker.sell(trade["id"],price); st.rerun()
            except Exception as e: st.error(str(e))
    else: st.caption("Record a simulated buy first to enable sell.")
if "closed_summary" in st.session_state:
    x=st.session_state["closed_summary"]
    st.divider()
    st.markdown('<div class="eyebrow">TRADE CLOSED · RESULT</div>',unsafe_allow_html=True)
    st.header(f"{'Profit' if x['pnl']>=0 else 'Loss'} · {x['symbol']}")
    st.caption("Gross paper result before brokerage, taxes, slippage and other charges.")
    q1,q2,q3,q4=st.columns(4)
    q1.metric("Realized P&L",money(x["pnl"]),f"{x['return_pct']:.2f}%")
    q2.metric("Quantity sold",f"{x['quantity']:,}")
    q3.metric("Buy price",money(x["buy_price"]))
    q4.metric("Sell price",money(x["sell_price"]))
    v1,v2=st.columns(2)
    v1.metric("Total buy value",money(x["buy_value"]))
    v2.metric("Total sell value",money(x["sell_value"]))
    if x["pnl"]>=0: st.success(f"Paper sell recorded. Gross profit: {money(x['pnl'])} ({x['return_pct']:.2f}%).")
    else: st.error(f"Paper sell recorded. Gross loss: {money(abs(x['pnl']))} ({x['return_pct']:.2f}%).")
    if st.button("Dismiss result summary"): del st.session_state["closed_summary"]; st.rerun()

st.markdown('<div class="eyebrow">AUTOMATION STATUS</div>', unsafe_allow_html=True)
remote_state = load_remote_scheduler_state()
if remote_state.get("symbol") and remote_state.get("status"):
    status = remote_state.get("status", "UNKNOWN")
    st.write(f"**Latest scheduled paper run:** {remote_state.get('symbol')} · {status.replace('_', ' ').title()}")
    if status == "SOLD":
        pcols = st.columns(4)
        pcols[0].metric("Scheduled gross P&L", money(remote_state.get("gross_pnl", 0)), f"{float(remote_state.get('return_pct', 0)):.2f}%")
        pcols[1].metric("Buy fill", money(remote_state.get("buy_fill_price", 0)))
        pcols[2].metric("Sell fill", money(remote_state.get("sell_fill_price", 0)))
        pcols[3].metric("Quantity", f"{int(remote_state.get('sell_fill_quantity', 0)):,}")
        st.caption(remote_state.get("message", "Paper sell completed."))
    else:
        st.caption(remote_state.get("message", "The scheduled runner has not completed a trade yet."))
else:
    st.caption("No scheduled trade result yet. The runner checks the shared plan on its next scheduled run.")

st.divider()
st.markdown('<div class="eyebrow">03 · PERFORMANCE</div>',unsafe_allow_html=True)
st.header("Trade journal")
history=broker.history()
if history.empty: st.info("Completed and open paper trades will appear here.")
else:
    display=history.rename(columns={"id":"Trade ID","symbol":"Symbol","side":"Side","quantity":"Quantity","entry_price":"Buy price (₹)","exit_price":"Sell price (₹)","pnl":"P&L (₹)","status":"Status","created_at":"Bought at","closed_at":"Sold at"})
    cols=[x for x in ["Trade ID","Symbol","Side","Quantity","Buy price (₹)","Sell price (₹)","P&L (₹)","Status","Bought at","Sold at"] if x in display.columns]
    st.dataframe(display[cols],hide_index=True,use_container_width=True)
    st.download_button("Download trade journal (CSV)",history.to_csv(index=False).encode("utf-8"),"northstar_paper_trade_journal.csv","text/csv")
    done=history[history.status=="CLOSED"].copy()
    if not done.empty:
        done["pnl"]=pd.to_numeric(done["pnl"],errors="coerce").fillna(0)
        st.subheader("Realized P&L by trade")
        st.bar_chart(done.reset_index(drop=True)["pnl"])

with st.expander("About this app & important limitations"):
    st.markdown("""
- **Paper trading only:** no broker integration and no real-money orders.
- **No indicators or signals:** plan-first workflow with manual simulated fills.
- **Price source:** Yahoo Finance; prices may be delayed, missing, or differ from broker execution prices.
- **P&L:** (sell price − buy price) × quantity; excludes fees and taxes.
- **Automation:** GitHub Actions checks the shared plan on a schedule and records simulated fills. Scheduled runs can be delayed or skipped; this is not a guarantee of execution at the exact minute. The app needs the TRADING_AGENT_GITHUB_TOKEN Codespaces secret to sync plans to the repository.
- **Storage:** the trade journal is in local SQLite. Some free hosts reset local files, so download backups regularly.
""")
st.caption("NORTHSTAR PAPER TRADING STUDIO · Designed for clarity, not financial advice.")
