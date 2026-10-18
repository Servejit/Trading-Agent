import sqlite3
from pathlib import Path
import pandas as pd

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

    def open_position(self, symbol, side, quantity, entry_price, stop_loss):
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL")
        if int(quantity) <= 0 or float(entry_price) <= 0:
            raise ValueError("Quantity and price must be positive")
        if self.get_open_position(symbol):
            raise ValueError("This symbol already has an open paper position")
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO trades(symbol, side, quantity, entry_price, stop_loss, status, reason) VALUES(?,?,?,?,?,'OPEN','Signal confirmed by user')",
                        (symbol, side, int(quantity), float(entry_price), float(stop_loss)))

    def get_open_position(self, symbol):
        with sqlite3.connect(self.db_path) as con:
            con.row_factory = sqlite3.Row
            row = con.execute("SELECT * FROM trades WHERE symbol=? AND status='OPEN' ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
            return dict(row) if row else None

    def close_position(self, symbol, exit_price, reason="Closed"):
        position = self.get_open_position(symbol)
        if not position:
            raise ValueError("No open paper position for this symbol")
        multiplier = 1 if position["side"] == "BUY" else -1
        pnl = (float(exit_price) - position["entry_price"]) * position["quantity"] * multiplier
        with sqlite3.connect(self.db_path) as con:
            con.execute("UPDATE trades SET exit_price=?, pnl=?, status='CLOSED', reason=?, closed_at=CURRENT_TIMESTAMP WHERE id=?",
                        (float(exit_price), pnl, reason, position["id"]))

    def history(self):
        with sqlite3.connect(self.db_path) as con:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", con)
