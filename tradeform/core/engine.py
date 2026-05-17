"""
Core trading engine — the orchestrator.
Ties together MT5, Ollama, indicators, risk, order flow, and the event bus.
"""

import time
from datetime import datetime
from typing import Optional, Dict, Any, List

from tradeform.config import AppConfig
from tradeform.core.events import EventBus, EventType, Event
from tradeform.mt5.connection import MT5Connection
from tradeform.mt5.data import MT5Data
from tradeform.mt5.trader import MT5Trader, TradeDirection, TradeResult
from tradeform.ai.ollama_client import OllamaClient
from tradeform.ai.analyst import AIAnalyst, TradeSignal
from tradeform.indicators.technical import compute_all_indicators
from tradeform.indicators.orderflow import (
    get_dom_snapshot,
    compute_order_flow,
    compute_volume_profile,
)
from tradeform.risk.manager import RiskManager
from tradeform.storage.logger import TradeLogger


class TradingEngine:
    """
    Main trading engine that orchestrates all modules.
    Used by the UI to drive everything.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.event_bus = EventBus()

        # Initialize modules
        self.mt5_conn = MT5Connection(config.mt5)
        self.mt5_data = MT5Data()
        self.mt5_trader = MT5Trader()
        self.ollama_client = OllamaClient(config.ollama)
        self.analyst = AIAnalyst(self.ollama_client)
        self.risk_manager = RiskManager(config.risk)
        self.logger = TradeLogger()

        # State
        self._last_analysis_time: Dict[str, float] = {}
        self._latest_signals: Dict[str, TradeSignal] = {}
        self._log_messages: List[str] = []

    # ── Connection Management ──────────────────────────────────

    def connect_mt5(self) -> bool:
        """Connect to MetaTrader 5."""
        try:
            result = self.mt5_conn.connect()
            if result:
                self.event_bus.emit_simple(EventType.MT5_CONNECTED)
                self._log("INFO", "engine", "MT5 connected successfully")

                # Enable symbols in Market Watch
                for symbol in self.config.trading.symbols:
                    self.mt5_data.ensure_symbol_visible(symbol)

            return result
        except Exception as e:
            self._log("ERROR", "engine", f"MT5 connection failed: {e}")
            self.event_bus.emit_simple(EventType.MT5_DISCONNECTED, error=str(e))
            return False

    def connect_ollama(self) -> bool:
        """Connect to Ollama."""
        try:
            result = self.ollama_client.connect()
            if result:
                self.event_bus.emit_simple(EventType.OLLAMA_CONNECTED)
                model = self.config.ollama.model
                available = self.ollama_client.is_model_available(model)
                if available:
                    self._log("INFO", "engine", f"Ollama connected, model '{model}' ready")
                else:
                    self._log("WARN", "engine", f"Ollama connected but model '{model}' not found")
            return result
        except Exception as e:
            self._log("ERROR", "engine", f"Ollama connection failed: {e}")
            self.event_bus.emit_simple(EventType.OLLAMA_DISCONNECTED, error=str(e))
            return False

    def disconnect(self):
        """Gracefully disconnect everything."""
        self.mt5_conn.disconnect()
        self._log("INFO", "engine", "Disconnected")

    # ── Data Access ────────────────────────────────────────────

    @property
    def mt5_connected(self) -> bool:
        return self.mt5_conn.connected

    @property
    def ollama_connected(self) -> bool:
        return self.ollama_client.connected

    def get_account_summary(self) -> Dict[str, Any]:
        """Get account info from MT5."""
        if not self.mt5_connected:
            return {
                "balance": 0, "equity": 0, "margin": 0,
                "free_margin": 0, "profit": 0, "leverage": 0,
                "currency": "USD", "name": "Disconnected",
            }
        return self.mt5_conn.get_account_summary()

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions."""
        if not self.mt5_connected:
            return []
        return self.mt5_data.get_positions()

    def get_tick(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get latest tick for a symbol."""
        if not self.mt5_connected:
            return None
        return self.mt5_data.get_tick(symbol)

    def get_multi_ticks(self) -> Dict[str, Dict[str, Any]]:
        """Get ticks for all configured symbols."""
        if not self.mt5_connected:
            return {}
        return self.mt5_data.get_multi_ticks(self.config.trading.symbols)

    def get_spread(self, symbol: str) -> float:
        """Get current spread for a symbol."""
        if not self.mt5_connected:
            return 0.0
        return self.mt5_data.get_spread(symbol)

    # ── AI Analysis ────────────────────────────────────────────

    def run_analysis(self, symbol: str) -> TradeSignal:
        """
        Run AI analysis on a symbol with DOM, Volume Profile, and Order Flow.
        Returns the generated TradeSignal.
        """
        if not self.mt5_connected:
            return TradeSignal(symbol=symbol, error="MT5 not connected")
        if not self.ollama_connected:
            return TradeSignal(symbol=symbol, error="Ollama not connected")

        self.event_bus.emit_simple(EventType.ANALYSIS_STARTED, symbol=symbol)
        self._log("INFO", "analyst", f"Analyzing {symbol} (DOM+OF+VP)...")

        # Fetch OHLCV data
        df = self.mt5_data.get_rates(
            symbol,
            self.config.trading.timeframe,
            count=200,
        )
        if df is None or len(df) < 50:
            signal = TradeSignal(symbol=symbol, error="Insufficient market data")
            self._log("ERROR", "analyst", f"Not enough data for {symbol}")
            return signal

        # Compute technical indicators
        indicators = compute_all_indicators(df)

        # Fetch DOM (Depth of Market / Level 2)
        try:
            dom_data = get_dom_snapshot(symbol)
            if dom_data.get("depth_levels", 0) > 0:
                self._log("INFO", "dom", f"DOM: {dom_data['dominant_side']} (imbalance: {dom_data['imbalance']:+.2f})")
            else:
                self._log("WARN", "dom", "DOM data unavailable for this symbol")
        except Exception as e:
            self._log("WARN", "dom", f"DOM fetch error: {e}")
            dom_data = {}

        # Compute Order Flow (tick-by-tick delta)
        try:
            order_flow = compute_order_flow(symbol, seconds=300)  # Last 5 minutes
            if order_flow.get("tick_count", 0) > 0:
                self._log("INFO", "flow", f"Delta: {order_flow['delta']:+.0f} | {order_flow['aggressor']}")
        except Exception as e:
            self._log("WARN", "flow", f"Order flow error: {e}")
            order_flow = {}

        # Compute Volume Profile
        try:
            volume_profile = compute_volume_profile(
                symbol,
                timeframe_str=self.config.trading.timeframe,
                bars=120,
            )
            if volume_profile.get("poc_price", 0) > 0:
                self._log("INFO", "vprofile",
                    f"POC: ${volume_profile['poc_price']:.2f} | "
                    f"VAH: ${volume_profile['vah']:.2f} | VAL: ${volume_profile['val']:.2f} | "
                    f"Position: {volume_profile['price_vs_value_area']}")
        except Exception as e:
            self._log("WARN", "vprofile", f"Volume profile error: {e}")
            volume_profile = {}

        # Get account context
        account = self.get_account_summary()
        positions = self.get_positions()
        risk_summary = self.risk_manager.get_risk_summary(account["balance"], positions)

        # Run AI analysis with all data streams
        signal = self.analyst.analyze(
            symbol=symbol,
            timeframe=self.config.trading.timeframe,
            indicators=indicators,
            account_info=account,
            positions=positions,
            daily_pnl=risk_summary["daily_pnl"],
            dom_data=dom_data,
            order_flow=order_flow,
            volume_profile=volume_profile,
        )

        # Store result
        self._latest_signals[symbol] = signal
        self._last_analysis_time[symbol] = time.time()

        # Log the analysis
        self.logger.log_analysis(
            symbol=symbol,
            timeframe=self.config.trading.timeframe,
            signal=signal.signal,
            confidence=signal.confidence,
            reasoning=signal.reasoning,
            raw_response=signal.raw_response,
        )

        self.event_bus.emit_simple(
            EventType.ANALYSIS_COMPLETE,
            symbol=symbol,
            signal=signal.signal,
            confidence=signal.confidence,
        )

        if signal.is_actionable:
            self.event_bus.emit_simple(
                EventType.NEW_SIGNAL,
                symbol=symbol,
                signal=signal.signal,
                confidence=signal.confidence,
            )
            self._log(
                "INFO", "analyst",
                f"Signal: {signal.signal} {symbol} "
                f"(confidence: {signal.confidence:.0%}, RR: {signal.risk_reward_ratio})",
            )
        else:
            self._log("INFO", "analyst", f"No actionable signal for {symbol}")

        return signal

    def get_latest_signal(self, symbol: str) -> Optional[TradeSignal]:
        """Get the most recent signal for a symbol."""
        return self._latest_signals.get(symbol)

    def should_analyze(self, symbol: str) -> bool:
        """Check if enough time has passed for a new analysis."""
        last = self._last_analysis_time.get(symbol, 0)
        interval = self.config.ollama.analysis_interval_minutes * 60
        return (time.time() - last) >= interval

    # ── Trade Execution ────────────────────────────────────────

    def execute_signal(self, signal: TradeSignal) -> TradeResult:
        """
        Execute a trade based on an AI signal.
        Validates through risk manager first.
        """
        if not signal.is_actionable:
            return TradeResult(success=False, message="Signal is not actionable")

        account = self.get_account_summary()
        positions = self.get_positions()

        # Get symbol info for position sizing
        sym_info = self.mt5_data.get_symbol_info(signal.symbol)
        if not sym_info:
            return TradeResult(success=False, message=f"Cannot get info for {signal.symbol}")

        # Calculate lot size from ATR-based SL
        sl_distance = abs(signal.entry_price - signal.stop_loss)
        if sl_distance > 0:
            volume = self.risk_manager.calculate_lot_size(
                account["balance"], sl_distance, sym_info,
            )
        else:
            volume = sym_info.get("volume_min", 0.01)

        # Validate through risk manager
        direction = signal.signal  # "BUY" or "SELL"
        risk_check = self.risk_manager.validate_trade(
            symbol=signal.symbol,
            direction=direction,
            volume=volume,
            balance=account["balance"],
            equity=account["equity"],
            open_positions=positions,
        )

        if not risk_check.approved:
            self._log("WARN", "risk", risk_check.reason)
            self.event_bus.emit_simple(
                EventType.TRADE_REJECTED,
                symbol=signal.symbol,
                reason=risk_check.reason,
            )
            return TradeResult(success=False, message=risk_check.reason)

        # Execute the trade
        trade_dir = TradeDirection.BUY if direction == "BUY" else TradeDirection.SELL
        result = self.mt5_trader.open_position(
            symbol=signal.symbol,
            direction=trade_dir,
            volume=volume,
            sl=signal.stop_loss,
            tp=signal.take_profit,
            comment=f"TF AI {signal.confidence:.0%}",
        )

        if result.success:
            self._log(
                "INFO", "trader",
                f"Opened {direction} {signal.symbol} {volume} lots @ {result.price}"
            )
            self.logger.log_trade(
                symbol=signal.symbol,
                direction=direction,
                volume=volume,
                entry_price=result.price,
                sl=signal.stop_loss,
                tp=signal.take_profit,
                ticket=result.order_ticket,
                ai_confidence=signal.confidence,
                ai_reasoning=signal.reasoning,
            )
            self.event_bus.emit_simple(
                EventType.TRADE_EXECUTED,
                symbol=signal.symbol,
                direction=direction,
                volume=volume,
                price=result.price,
                ticket=result.order_ticket,
            )
        else:
            self._log("ERROR", "trader", f"Trade failed: {result.message}")

        return result

    def close_position(self, ticket: int) -> TradeResult:
        """Close a specific position by ticket."""
        result = self.mt5_trader.close_position(ticket)
        if result.success:
            self._log("INFO", "trader", f"Closed position #{ticket}")
            self.event_bus.emit_simple(
                EventType.TRADE_CLOSED,
                ticket=ticket,
            )
        else:
            self._log("ERROR", "trader", f"Failed to close #{ticket}: {result.message}")
        return result

    def close_all_positions(self) -> List[TradeResult]:
        """Emergency close all positions (kill switch)."""
        self.risk_manager.kill_switch_on()
        results = self.mt5_trader.close_all()
        self._log("WARN", "engine", f"🛑 KILL SWITCH: Closed {len(results)} positions")
        self.event_bus.emit_simple(EventType.KILL_SWITCH, count=len(results))
        return results

    def manage_open_positions(self):
        """
        Actively manage open positions for gold scalping.
        - Tight trailing stops using real ATR from market data
        - Move to breakeven once price moves 1x ATR in favor
        - Auto-close stale scalps sitting with small profit
        """
        if not self.mt5_connected:
            return

        positions = self.get_positions()

        for pos in positions:
            symbol = pos.get("symbol", "")
            ticket = pos.get("ticket", 0)
            profit = pos.get("profit", 0)
            current_sl = pos.get("sl", 0)
            entry_price = pos.get("price_open", 0)
            pos_type = pos.get("type", 0)  # 0=BUY, 1=SELL
            open_time = pos.get("time", 0)

            # Get current price
            tick = self.get_tick(symbol)
            if not tick:
                continue

            current_price = tick.get("bid", 0) if pos_type == 0 else tick.get("ask", 0)

            # Get symbol info
            sym_info = self.mt5_data.get_symbol_info(symbol)
            if not sym_info:
                continue

            digits = sym_info.get("digits", 2)
            point = sym_info.get("point", 0.01)

            # Calculate real ATR from recent M1 bars
            try:
                df = self.mt5_data.get_rates(symbol, self.config.trading.timeframe, count=20)
                if df is not None and len(df) >= 14:
                    from tradeform.indicators.technical import atr as calc_atr
                    import numpy as np
                    high = df["high"].values.astype(float)
                    low = df["low"].values.astype(float)
                    close = df["close"].values.astype(float)
                    atr_values = calc_atr(high, low, close, 14)
                    valid_atr = atr_values[~np.isnan(atr_values)]
                    current_atr = float(valid_atr[-1]) if len(valid_atr) > 0 else 2.0  # Gold default ~$2
                else:
                    current_atr = 2.0  # Fallback for gold
            except Exception:
                current_atr = 2.0

            # Trailing distance = 0.75x ATR (tighter for scalping)
            trail_distance = current_atr * 0.75

            # Price distance from entry
            if pos_type == 0:  # BUY
                price_in_favor = current_price - entry_price
            else:  # SELL
                price_in_favor = entry_price - current_price

            # Move to breakeven when price moves 1x ATR in favor
            if price_in_favor >= current_atr and entry_price > 0:
                if pos_type == 0:  # BUY — SL should be at or above entry
                    breakeven_sl = entry_price + (point * 10)  # +10 points above entry
                    if current_sl < breakeven_sl:
                        result = self.mt5_trader.modify_position(ticket, sl=round(breakeven_sl, digits))
                        if result.success:
                            self._log("INFO", "scalp", f"🔒 Breakeven #{ticket} {symbol} SL→{breakeven_sl:.{digits}f}")
                        continue
                else:  # SELL — SL should be at or below entry
                    breakeven_sl = entry_price - (point * 10)
                    if current_sl == 0 or current_sl > breakeven_sl:
                        result = self.mt5_trader.modify_position(ticket, sl=round(breakeven_sl, digits))
                        if result.success:
                            self._log("INFO", "scalp", f"🔒 Breakeven #{ticket} {symbol} SL→{breakeven_sl:.{digits}f}")
                        continue

            # Trail stop on winning positions (only after breakeven)
            if profit > 0 and price_in_favor > current_atr * 1.5:
                if pos_type == 0:  # BUY
                    new_sl = current_price - trail_distance
                    if new_sl > current_sl and new_sl > entry_price:
                        result = self.mt5_trader.modify_position(ticket, sl=round(new_sl, digits))
                        if result.success:
                            self._log("INFO", "scalp", f"📈 Trail #{ticket} {symbol} SL→{new_sl:.{digits}f} (+${profit:.2f})")
                else:  # SELL
                    new_sl = current_price + trail_distance
                    if current_sl == 0 or (new_sl < current_sl and new_sl < entry_price):
                        result = self.mt5_trader.modify_position(ticket, sl=round(new_sl, digits))
                        if result.success:
                            self._log("INFO", "scalp", f"📈 Trail #{ticket} {symbol} SL→{new_sl:.{digits}f} (+${profit:.2f})")

    def close_symbol_positions(self, symbol: str, direction: str = None) -> List[TradeResult]:
        """
        Close all positions on a specific symbol.
        Optionally filter by direction (BUY/SELL).
        """
        positions = self.get_positions()
        results = []
        for pos in positions:
            if pos.get("symbol") != symbol:
                continue
            if direction:
                pos_dir = "BUY" if pos.get("type") == 0 else "SELL"
                if pos_dir != direction:
                    continue
            result = self.close_position(pos.get("ticket", 0))
            results.append(result)
        return results

    # ── Chat ───────────────────────────────────────────────────

    def chat(self, message: str) -> str:
        """Send a message to the AI assistant."""
        if not self.ollama_connected:
            return "⚠️ Ollama is not connected."

        account = self.get_account_summary()
        context = {
            "symbols": self.config.trading.symbols,
            "mode": self.config.trading.mode,
            "balance": account["balance"],
        }
        return self.analyst.chat(message, context)

    # ── Logging ────────────────────────────────────────────────

    def _log(self, level: str, module: str, message: str):
        """Internal logging — stores messages and logs to DB."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] [{level}] [{module}] {message}"
        self._log_messages.append(log_line)

        # Keep only last 200 messages in memory
        if len(self._log_messages) > 200:
            self._log_messages = self._log_messages[-200:]

        # Persist to DB
        try:
            self.logger.log_system(level, module, message)
        except Exception:
            pass  # Don't crash on log failure

    def get_logs(self, limit: int = 50) -> List[str]:
        """Get recent log messages for display."""
        return self._log_messages[-limit:]

    def get_daily_stats(self) -> Dict[str, Any]:
        """Get today's trading statistics."""
        return self.logger.get_daily_stats()
