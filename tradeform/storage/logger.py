"""
Trade journal and performance logger.
Stores trades, AI analyses, and daily stats in SQLite.
"""

import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List


class TradeLogger:
    """SQLite-based trade journal."""

    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, "tradeform.db")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Create tables if they don't exist."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                volume REAL NOT NULL,
                entry_price REAL,
                exit_price REAL,
                sl REAL,
                tp REAL,
                pnl REAL DEFAULT 0,
                status TEXT DEFAULT 'OPEN',
                ticket INTEGER,
                ai_confidence REAL,
                ai_reasoning TEXT,
                comment TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timeframe TEXT,
                signal TEXT,
                confidence REAL,
                reasoning TEXT,
                raw_response TEXT,
                executed INTEGER DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE NOT NULL,
                trades_count INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                total_pnl REAL DEFAULT 0,
                max_drawdown REAL DEFAULT 0
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                level TEXT NOT NULL,
                module TEXT,
                message TEXT NOT NULL
            )
        """)

        conn.commit()
        conn.close()

    def log_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        entry_price: float = 0,
        sl: float = 0,
        tp: float = 0,
        ticket: int = 0,
        ai_confidence: float = 0,
        ai_reasoning: str = "",
        comment: str = "",
    ) -> int:
        """Log a new trade. Returns the row ID."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """INSERT INTO trades 
               (timestamp, symbol, direction, volume, entry_price, sl, tp, ticket, 
                ai_confidence, ai_reasoning, comment, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN')""",
            (
                datetime.now().isoformat(),
                symbol,
                direction,
                volume,
                entry_price,
                sl,
                tp,
                ticket,
                ai_confidence,
                ai_reasoning,
                comment,
            ),
        )
        row_id = c.lastrowid
        conn.commit()
        conn.close()
        return row_id

    def close_trade(self, ticket: int, exit_price: float, pnl: float):
        """Update a trade as closed with exit price and P/L."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """UPDATE trades SET exit_price = ?, pnl = ?, status = 'CLOSED'
               WHERE ticket = ? AND status = 'OPEN'""",
            (exit_price, pnl, ticket),
        )
        conn.commit()
        conn.close()

    def log_analysis(
        self,
        symbol: str,
        timeframe: str,
        signal: str,
        confidence: float,
        reasoning: str,
        raw_response: str = "",
        executed: bool = False,
    ):
        """Log an AI analysis result."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """INSERT INTO ai_analyses 
               (timestamp, symbol, timeframe, signal, confidence, reasoning, raw_response, executed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now().isoformat(),
                symbol,
                timeframe,
                signal,
                confidence,
                reasoning,
                raw_response,
                1 if executed else 0,
            ),
        )
        conn.commit()
        conn.close()

    def log_system(self, level: str, module: str, message: str):
        """Log a system event."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(
            """INSERT INTO system_logs (timestamp, level, module, message)
               VALUES (?, ?, ?, ?)""",
            (datetime.now().isoformat(), level, module, message),
        )
        conn.commit()
        conn.close()

    def get_recent_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent trades."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_recent_analyses(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent AI analyses."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM ai_analyses ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent system logs."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute(
            "SELECT * FROM system_logs ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def get_daily_stats(self) -> Dict[str, Any]:
        """Get today's trading stats."""
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # Count today's trades
        c.execute(
            "SELECT COUNT(*) as count FROM trades WHERE timestamp LIKE ?",
            (f"{today}%",),
        )
        count = c.fetchone()["count"]

        # Calculate wins/losses
        c.execute(
            "SELECT COUNT(*) as wins FROM trades WHERE timestamp LIKE ? AND pnl > 0 AND status='CLOSED'",
            (f"{today}%",),
        )
        wins = c.fetchone()["wins"]

        c.execute(
            "SELECT COALESCE(SUM(pnl), 0) as total FROM trades WHERE timestamp LIKE ? AND status='CLOSED'",
            (f"{today}%",),
        )
        total_pnl = c.fetchone()["total"]

        conn.close()

        return {
            "date": today,
            "trades": count,
            "wins": wins,
            "losses": count - wins if count > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round((wins / count) * 100, 1) if count > 0 else 0,
        }
