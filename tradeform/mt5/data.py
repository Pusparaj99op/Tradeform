"""
MetaTrader 5 market data fetcher.
Provides OHLCV bars, live ticks, positions, and trade history.
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from tradeform.mt5.connection import TIMEFRAME_MAP


class MT5Data:
    """Fetches market data from the MT5 terminal."""

    @staticmethod
    def get_rates(
        symbol: str,
        timeframe: str = "M15",
        count: int = 200,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch OHLCV bars for a symbol.
        Returns DataFrame with columns: time, open, high, low, close, tick_volume, spread.
        """
        tf = TIMEFRAME_MAP.get(timeframe)
        if tf is None:
            raise ValueError(f"Invalid timeframe: {timeframe}. Use: {list(TIMEFRAME_MAP.keys())}")

        rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if rates is None or len(rates) == 0:
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    @staticmethod
    def get_tick(symbol: str) -> Optional[Dict[str, Any]]:
        """Get the latest tick for a symbol (bid, ask, last, volume)."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        return tick._asdict()

    @staticmethod
    def get_symbol_info(symbol: str) -> Optional[Dict[str, Any]]:
        """Get symbol properties (digits, point, lot sizes, etc.)."""
        info = mt5.symbol_info(symbol)
        if info is None:
            # Try to enable the symbol first
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
            if info is None:
                return None
        return info._asdict()

    @staticmethod
    def get_spread(symbol: str) -> float:
        """Get current spread in points."""
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return 0.0
        info = mt5.symbol_info(symbol)
        if info is None:
            return 0.0
        return round((tick.ask - tick.bid) / info.point, 1)

    @staticmethod
    def get_positions(symbol: str = None) -> List[Dict[str, Any]]:
        """
        Get open positions.
        If symbol is provided, filters by that symbol.
        """
        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        return [p._asdict() for p in positions]

    @staticmethod
    def get_total_positions() -> int:
        """Get total number of open positions."""
        positions = mt5.positions_total()
        return positions if positions is not None else 0

    @staticmethod
    def get_orders(symbol: str = None) -> List[Dict[str, Any]]:
        """Get pending orders."""
        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()

        if orders is None:
            return []

        return [o._asdict() for o in orders]

    @staticmethod
    def get_history(
        symbol: str = None,
        days: int = 1,
    ) -> List[Dict[str, Any]]:
        """Get closed trade history for the past N days."""
        date_to = datetime.now()
        date_from = date_to - timedelta(days=days)

        if symbol:
            deals = mt5.history_deals_get(date_from, date_to, group=f"*{symbol}*")
        else:
            deals = mt5.history_deals_get(date_from, date_to)

        if deals is None:
            return []

        return [d._asdict() for d in deals]

    @staticmethod
    def ensure_symbol_visible(symbol: str) -> bool:
        """Make sure a symbol is visible in Market Watch."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return False
        if not info.visible:
            mt5.symbol_select(symbol, True)
        return True

    @staticmethod
    def get_multi_ticks(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get latest ticks for multiple symbols at once."""
        result = {}
        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                result[symbol] = tick._asdict()
        return result
