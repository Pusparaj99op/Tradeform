"""
MetaTrader 5 trade execution module.
Handles opening, modifying, and closing positions.
"""

import MetaTrader5 as mt5
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass
from enum import Enum


class TradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class TradeResult:
    """Result of a trade operation."""
    success: bool
    order_ticket: int = 0
    message: str = ""
    retcode: int = 0
    volume: float = 0.0
    price: float = 0.0

    def __str__(self):
        if self.success:
            return f"✅ Order #{self.order_ticket} executed at {self.price} ({self.volume} lots)"
        return f"❌ Trade failed: {self.message} (code: {self.retcode})"


# MT5 error code descriptions
RETCODE_MESSAGES = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10008: "Order placed",
    10009: "Request completed (trade executed)",
    10010: "Request partially filled",
    10011: "Request processing error",
    10012: "Request canceled by timeout",
    10013: "Invalid request",
    10014: "Invalid volume",
    10015: "Invalid price",
    10016: "Invalid stops",
    10017: "Trade disabled",
    10018: "Market closed",
    10019: "Not enough money",
    10020: "Price changed",
    10021: "No quotes",
    10022: "Order busy processing",
    10024: "Too frequent requests",
    10025: "No changes in request",
    10026: "Autotrading disabled by server",
    10027: "Autotrading disabled by client",
    10030: "Invalid fill type",
    10031: "No connection to trade server",
    10033: "Unsupported fill type",
}


class MT5Trader:
    """Executes trades on the MT5 terminal."""

    @staticmethod
    def _get_filling_type(symbol: str) -> int:
        """Determine the correct filling type for a symbol."""
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC

        filling = info.filling_mode
        if filling & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        elif filling & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        else:
            return mt5.ORDER_FILLING_RETURN

    @staticmethod
    def open_position(
        symbol: str,
        direction: TradeDirection,
        volume: float,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "Tradeform",
        deviation: int = 20,
        magic: int = 123456,
    ) -> TradeResult:
        """
        Open a new market position.
        
        Args:
            symbol: Trading symbol (e.g., "EURUSD")
            direction: BUY or SELL
            volume: Lot size
            sl: Stop loss price (0 = no SL)
            tp: Take profit price (0 = no TP)
            comment: Order comment
            deviation: Max price deviation in points
            magic: Expert Advisor magic number
        """
        # Get current price
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return TradeResult(success=False, message=f"Cannot get tick for {symbol}")

        if direction == TradeDirection.BUY:
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid

        # Build request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": deviation,
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": MT5Trader._get_filling_type(symbol),
        }

        # Send order
        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            return TradeResult(
                success=False,
                message=f"order_send returned None: {error}",
            )

        retcode = result.retcode
        if retcode == mt5.TRADE_RETCODE_DONE:
            return TradeResult(
                success=True,
                order_ticket=result.order,
                message="Trade executed successfully",
                retcode=retcode,
                volume=result.volume,
                price=result.price,
            )
        else:
            msg = RETCODE_MESSAGES.get(retcode, f"Unknown error code {retcode}")
            return TradeResult(
                success=False,
                order_ticket=result.order,
                message=msg,
                retcode=retcode,
            )

    @staticmethod
    def close_position(ticket: int, deviation: int = 20) -> TradeResult:
        """Close an open position by ticket number."""
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return TradeResult(
                success=False,
                message=f"Position #{ticket} not found",
            )

        pos = position[0]
        symbol = pos.symbol
        volume = pos.volume

        # Reverse the direction to close
        if pos.type == mt5.ORDER_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            tick = mt5.symbol_info_tick(symbol)
            price = tick.bid if tick else 0
        else:
            order_type = mt5.ORDER_TYPE_BUY
            tick = mt5.symbol_info_tick(symbol)
            price = tick.ask if tick else 0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "position": ticket,
            "price": price,
            "deviation": deviation,
            "magic": pos.magic,
            "comment": "Tradeform close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": MT5Trader._get_filling_type(symbol),
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            return TradeResult(success=False, message=f"Close failed: {error}")

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return TradeResult(
                success=True,
                order_ticket=result.order,
                message=f"Position #{ticket} closed",
                retcode=result.retcode,
                volume=result.volume,
                price=result.price,
            )
        else:
            msg = RETCODE_MESSAGES.get(result.retcode, f"Error {result.retcode}")
            return TradeResult(success=False, message=msg, retcode=result.retcode)

    @staticmethod
    def close_all(symbol: str = None, magic: int = None) -> list:
        """
        Close all open positions.
        Optionally filter by symbol or magic number.
        """
        positions = mt5.positions_get()
        if positions is None or len(positions) == 0:
            return []

        results = []
        for pos in positions:
            if symbol and pos.symbol != symbol:
                continue
            if magic and pos.magic != magic:
                continue
            result = MT5Trader.close_position(pos.ticket)
            results.append(result)

        return results

    @staticmethod
    def modify_position(
        ticket: int,
        sl: float = None,
        tp: float = None,
    ) -> TradeResult:
        """Modify SL/TP of an existing position."""
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return TradeResult(success=False, message=f"Position #{ticket} not found")

        pos = position[0]

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": pos.symbol,
            "position": ticket,
            "sl": sl if sl is not None else pos.sl,
            "tp": tp if tp is not None else pos.tp,
        }

        result = mt5.order_send(request)
        if result is None:
            error = mt5.last_error()
            return TradeResult(success=False, message=f"Modify failed: {error}")

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return TradeResult(
                success=True,
                order_ticket=ticket,
                message=f"Position #{ticket} modified (SL={sl}, TP={tp})",
                retcode=result.retcode,
            )
        else:
            msg = RETCODE_MESSAGES.get(result.retcode, f"Error {result.retcode}")
            return TradeResult(success=False, message=msg, retcode=result.retcode)
