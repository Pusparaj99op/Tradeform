"""
AI market analyst.
Orchestrates data collection, indicator computation, AI analysis, and signal parsing.
"""

import json
import re
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass, field

from tradeform.ai.ollama_client import OllamaClient
from tradeform.ai.prompts import SYSTEM_PROMPT, ANALYSIS_PROMPT, CHAT_PROMPT
from tradeform.config import OllamaConfig


@dataclass
class TradeSignal:
    """Structured trade signal from AI analysis."""
    symbol: str = ""
    timeframe: str = ""
    signal: str = "HOLD"          # BUY, SELL, HOLD
    confidence: float = 0.0       # 0.0 to 1.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    reasoning: str = ""
    key_factors: List[str] = field(default_factory=list)
    raw_response: str = ""
    error: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.signal in ("BUY", "SELL") and self.confidence >= 0.6

    @property
    def risk_reward_ratio(self) -> float:
        if self.stop_loss == 0 or self.entry_price == 0 or self.take_profit == 0:
            return 0.0
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return round(reward / risk, 2) if risk > 0 else 0.0


class AIAnalyst:
    """AI-powered market analyst using Ollama."""

    def __init__(self, client: OllamaClient):
        self.client = client
        self._conversation_history: List[Dict[str, str]] = []

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        indicators: Dict[str, Any],
        account_info: Dict[str, Any] = None,
        positions: List[Dict[str, Any]] = None,
        daily_pnl: float = 0.0,
    ) -> TradeSignal:
        """
        Perform full market analysis and return a trade signal.
        
        Args:
            symbol: Trading symbol
            timeframe: Chart timeframe
            indicators: Dict from compute_all_indicators()
            account_info: Account balance/equity info
            positions: Current open positions
            daily_pnl: Running daily P/L
        """
        account_info = account_info or {}
        positions = positions or []

        # Format last 5 candles
        candles_text = ""
        for i, c in enumerate(indicators.get("last_5_candles", []), 1):
            candles_text += f"  {i}. O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}\n"

        # Format positions
        positions_text = "None"
        if positions:
            pos_lines = []
            for p in positions:
                direction = "BUY" if p.get("type") == 0 else "SELL"
                pos_lines.append(
                    f"{p.get('symbol')} {direction} {p.get('volume')} lots, P/L: ${p.get('profit', 0):.2f}"
                )
            positions_text = "; ".join(pos_lines)

        # Build the analysis prompt
        macd_data = indicators.get("macd", {})
        bb_data = indicators.get("bollinger", {})
        sr_data = indicators.get("support_resistance", {})

        prompt = ANALYSIS_PROMPT.format(
            symbol=symbol,
            timeframe=timeframe,
            current_price=indicators.get("current_price", "N/A"),
            previous_close=indicators.get("previous_close", "N/A"),
            trend=indicators.get("trend", "UNKNOWN"),
            rsi_14=indicators.get("rsi_14", "N/A"),
            macd_line=macd_data.get("line", "N/A"),
            macd_signal=macd_data.get("signal", "N/A"),
            macd_histogram=macd_data.get("histogram", "N/A"),
            atr_14=indicators.get("atr_14", "N/A"),
            ema_20=indicators.get("ema_20", "N/A"),
            ema_50=indicators.get("ema_50", "N/A"),
            ema_200=indicators.get("ema_200", "N/A"),
            bb_upper=bb_data.get("upper", "N/A"),
            bb_middle=bb_data.get("middle", "N/A"),
            bb_lower=bb_data.get("lower", "N/A"),
            resistance_1=sr_data.get("resistance_1", "N/A"),
            resistance_2=sr_data.get("resistance_2", "N/A"),
            support_1=sr_data.get("support_1", "N/A"),
            support_2=sr_data.get("support_2", "N/A"),
            pivot=sr_data.get("pivot", "N/A"),
            volume_current=indicators.get("volume_current", "N/A"),
            volume_avg_20=indicators.get("volume_avg_20", "N/A"),
            last_5_candles=candles_text,
            open_positions=positions_text,
            balance=account_info.get("balance", 0),
            daily_pnl=daily_pnl,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        # Get AI response
        try:
            response = self.client.chat(messages)
            return self._parse_signal(response, symbol, timeframe)
        except Exception as e:
            return TradeSignal(
                symbol=symbol,
                timeframe=timeframe,
                error=str(e),
            )

    def analyze_stream(
        self,
        symbol: str,
        timeframe: str,
        indicators: Dict[str, Any],
        account_info: Dict[str, Any] = None,
        positions: List[Dict[str, Any]] = None,
        daily_pnl: float = 0.0,
    ) -> Generator[str, None, None]:
        """
        Stream the AI analysis response token by token.
        Yields text chunks. Final chunk will be the complete response.
        """
        account_info = account_info or {}
        positions = positions or []

        # Format data (same as analyze)
        candles_text = ""
        for i, c in enumerate(indicators.get("last_5_candles", []), 1):
            candles_text += f"  {i}. O:{c['open']} H:{c['high']} L:{c['low']} C:{c['close']}\n"

        positions_text = "None"
        if positions:
            pos_lines = []
            for p in positions:
                direction = "BUY" if p.get("type") == 0 else "SELL"
                pos_lines.append(f"{p.get('symbol')} {direction} {p.get('volume')} lots")
            positions_text = "; ".join(pos_lines)

        macd_data = indicators.get("macd", {})
        bb_data = indicators.get("bollinger", {})
        sr_data = indicators.get("support_resistance", {})

        prompt = ANALYSIS_PROMPT.format(
            symbol=symbol,
            timeframe=timeframe,
            current_price=indicators.get("current_price", "N/A"),
            previous_close=indicators.get("previous_close", "N/A"),
            trend=indicators.get("trend", "UNKNOWN"),
            rsi_14=indicators.get("rsi_14", "N/A"),
            macd_line=macd_data.get("line", "N/A"),
            macd_signal=macd_data.get("signal", "N/A"),
            macd_histogram=macd_data.get("histogram", "N/A"),
            atr_14=indicators.get("atr_14", "N/A"),
            ema_20=indicators.get("ema_20", "N/A"),
            ema_50=indicators.get("ema_50", "N/A"),
            ema_200=indicators.get("ema_200", "N/A"),
            bb_upper=bb_data.get("upper", "N/A"),
            bb_middle=bb_data.get("middle", "N/A"),
            bb_lower=bb_data.get("lower", "N/A"),
            resistance_1=sr_data.get("resistance_1", "N/A"),
            resistance_2=sr_data.get("resistance_2", "N/A"),
            support_1=sr_data.get("support_1", "N/A"),
            support_2=sr_data.get("support_2", "N/A"),
            pivot=sr_data.get("pivot", "N/A"),
            volume_current=indicators.get("volume_current", "N/A"),
            volume_avg_20=indicators.get("volume_avg_20", "N/A"),
            last_5_candles=candles_text,
            open_positions=positions_text,
            balance=account_info.get("balance", 0),
            daily_pnl=daily_pnl,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        yield from self.client.chat_stream(messages)

    def chat(self, user_message: str, context: Dict[str, Any] = None) -> str:
        """
        Interactive chat with the AI for ad-hoc questions.
        Maintains conversation history for context.
        """
        context = context or {}
        
        system = CHAT_PROMPT.format(
            symbols=", ".join(context.get("symbols", ["N/A"])),
            mode=context.get("mode", "confirmation"),
            balance=context.get("balance", 0),
        )

        self._conversation_history.append({"role": "user", "content": user_message})

        messages = [
            {"role": "system", "content": system},
            *self._conversation_history[-10:],  # Keep last 10 messages for context
        ]

        response = self.client.chat(messages)
        self._conversation_history.append({"role": "assistant", "content": response})

        return response

    def clear_history(self):
        """Clear conversation history."""
        self._conversation_history.clear()

    def _parse_signal(self, response: str, symbol: str, timeframe: str) -> TradeSignal:
        """Parse JSON signal from AI response."""
        signal = TradeSignal(symbol=symbol, timeframe=timeframe, raw_response=response)

        try:
            # Try to extract JSON from response (may be wrapped in markdown code blocks)
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if not json_match:
                signal.error = "No JSON found in response"
                signal.reasoning = response[:500]
                return signal

            data = json.loads(json_match.group())

            signal.signal = data.get("signal", "HOLD").upper()
            signal.confidence = float(data.get("confidence", 0.0))
            signal.entry_price = float(data.get("entry_price", 0.0))
            signal.stop_loss = float(data.get("stop_loss", 0.0))
            signal.take_profit = float(data.get("take_profit", 0.0))
            signal.reasoning = data.get("reasoning", "")
            signal.key_factors = data.get("key_factors", [])

        except json.JSONDecodeError as e:
            signal.error = f"JSON parse error: {e}"
            signal.reasoning = response[:500]
        except Exception as e:
            signal.error = f"Parse error: {e}"

        return signal
