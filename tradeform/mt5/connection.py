"""
MetaTrader 5 connection manager.
Handles initialization, login, health checks, and shutdown.
"""

import MetaTrader5 as mt5
from datetime import datetime
from typing import Optional, Dict, Any

from tradeform.config import MT5Config


# Timeframe mapping from string to MT5 constant
TIMEFRAME_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}


class MT5Connection:
    """Manages the connection to the MetaTrader 5 terminal."""

    def __init__(self, config: MT5Config):
        self.config = config
        self._connected = False

    @property
    def connected(self) -> bool:
        """Check if MT5 terminal is connected."""
        if not self._connected:
            return False
        # Verify the connection is still alive
        info = mt5.terminal_info()
        if info is None:
            self._connected = False
            return False
        return True

    def connect(self) -> bool:
        """
        Initialize and connect to the MT5 terminal.
        Returns True on success.
        """
        # Build init kwargs
        kwargs: Dict[str, Any] = {}
        if self.config.path:
            kwargs["path"] = self.config.path

        if self.config.login and self.config.login > 0:
            kwargs["login"] = self.config.login
            kwargs["password"] = self.config.password
            kwargs["server"] = self.config.server

        # Initialize MT5
        if not mt5.initialize(**kwargs):
            error = mt5.last_error()
            raise ConnectionError(
                f"MT5 initialization failed: {error}"
            )

        # If login credentials provided but not passed to initialize, do explicit login
        if self.config.login and self.config.login > 0 and "login" not in kwargs:
            if not mt5.login(
                login=self.config.login,
                password=self.config.password,
                server=self.config.server,
            ):
                error = mt5.last_error()
                mt5.shutdown()
                raise ConnectionError(
                    f"MT5 login failed: {error}"
                )

        self._connected = True
        return True

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self._connected:
            mt5.shutdown()
            self._connected = False

    def get_terminal_info(self) -> Optional[Dict[str, Any]]:
        """Get terminal information."""
        if not self.connected:
            return None
        info = mt5.terminal_info()
        if info is None:
            return None
        return info._asdict()

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """
        Get account information.
        Returns dict with balance, equity, margin, free_margin, etc.
        """
        if not self.connected:
            return None
        info = mt5.account_info()
        if info is None:
            return None
        return info._asdict()

    def get_account_summary(self) -> Dict[str, Any]:
        """Get a concise account summary for display."""
        info = self.get_account_info()
        if not info:
            return {
                "balance": 0.0,
                "equity": 0.0,
                "margin": 0.0,
                "free_margin": 0.0,
                "profit": 0.0,
                "leverage": 0,
                "currency": "USD",
                "name": "Disconnected",
            }
        return {
            "balance": info.get("balance", 0.0),
            "equity": info.get("equity", 0.0),
            "margin": info.get("margin", 0.0),
            "free_margin": info.get("margin_free", 0.0),
            "profit": info.get("profit", 0.0),
            "leverage": info.get("leverage", 0),
            "currency": info.get("currency", "USD"),
            "name": info.get("name", ""),
        }
