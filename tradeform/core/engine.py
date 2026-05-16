"""
Core trading engine — the orchestrator.
Ties together MT5, Ollama, indicators, risk, and the event bus.
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
        Run AI analysis on a symbol.
        Returns the generated TradeSignal.
        """
        if not self.mt5_connected:
            return TradeSignal(symbol=symbol, error="MT5 not connected")
        if not self.ollama_connected:
            return TradeSignal(symbol=symbol, error="Ollama not connected")

        self.event_bus.emit_simple(EventType.ANALYSIS_STARTED, symbol=symbol)
        self._log("INFO", "analyst", f"Analyzing {symbol}...")

        # Fetch data
        df = self.mt5_data.get_rates(
            symbol,
            self.config.trading.timeframe,
            count=200,
        )
        if df is None or len(df) < 50:
            signal = TradeSignal(symbol=symbol, error="Insufficient market data")
            self._log("ERROR", "analyst", f"Not enough data for {symbol}")
            return signal

        # Compute indicators
        indicators = compute_all_indicators(df)

        # Get account context
        account = self.get_account_summary()
        positions = self.get_positions()
        risk_summary = self.risk_manager.get_risk_summary(account["balance"], positions)

        # Run AI analysis
        signal = self.analyst.analyze(
            symbol=symbol,
            timeframe=self.config.trading.timeframe,
            indicators=indicators,
            account_info=account,
            positions=positions,
            daily_pnl=risk_summary["daily_pnl"],
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
