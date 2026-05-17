"""
AI market analyst.
Orchestrates data collection, indicator computation, AI analysis, and signal parsing.
Enhanced with DOM, Volume Profile, and Order Flow for institutional-grade gold scalping.
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
        return self.signal in ("BUY", "SELL") and self.confidence >= 0.4

    @property
    def risk_reward_ratio(self) -> float:
        if self.stop_loss == 0 or self.entry_price == 0 or self.take_profit == 0:
            return 0.0
        risk = abs(self.entry_price - self.stop_loss)
        reward = abs(self.take_profit - self.entry_price)
        return round(reward / risk, 2) if risk > 0 else 0.0


class AIAnalyst:
    """AI-powered market analyst using Ollama with order flow intelligence."""

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
        dom_data: Dict[str, Any] = None,
        order_flow: Dict[str, Any] = None,
        volume_profile: Dict[str, Any] = None,
    ) -> TradeSignal:
        """
        Perform full market analysis with order flow and return a trade signal.
        """
        account_info = account_info or {}
        positions = positions or []
        dom_data = dom_data or {}
        order_flow = order_flow or {}
        volume_profile = volume_profile or {}

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

        # Build the analysis prompt with all data streams
        prompt = self._build_prompt(
            symbol, timeframe, indicators, account_info,
            positions_text, candles_text, daily_pnl,
            dom_data, order_flow, volume_profile,
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
        dom_data: Dict[str, Any] = None,
        order_flow: Dict[str, Any] = None,
        volume_profile: Dict[str, Any] = None,
    ) -> Generator[str, None, None]:
        """Stream the AI analysis response token by token."""
        account_info = account_info or {}
        positions = positions or []
        dom_data = dom_data or {}
        order_flow = order_flow or {}
        volume_profile = volume_profile or {}

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

        prompt = self._build_prompt(
            symbol, timeframe, indicators, account_info,
            positions_text, candles_text, daily_pnl,
            dom_data, order_flow, volume_profile,
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        yield from self.client.chat_stream(messages)

    def _build_prompt(
        self,
        symbol: str,
        timeframe: str,
        indicators: Dict[str, Any],
        account_info: Dict[str, Any],
        positions_text: str,
        candles_text: str,
        daily_pnl: float,
        dom_data: Dict[str, Any],
        order_flow: Dict[str, Any],
        volume_profile: Dict[str, Any],
    ) -> str:
        """Build the complete analysis prompt with all data streams."""
        macd_data = indicators.get("macd", {})
        bb_data = indicators.get("bollinger", {})
        sr_data = indicators.get("support_resistance", {})

        # Format DOM bid/ask levels
        dom_bid_lines = ""
        for lvl in dom_data.get("bid_levels", []):
            dom_bid_lines += f"  ${lvl['price']:.2f} — {lvl['volume']} lots\n"
        if not dom_bid_lines:
            dom_bid_lines = "  (DOM data unavailable)\n"

        dom_ask_lines = ""
        for lvl in dom_data.get("ask_levels", []):
            dom_ask_lines += f"  ${lvl['price']:.2f} — {lvl['volume']} lots\n"
        if not dom_ask_lines:
            dom_ask_lines = "  (DOM data unavailable)\n"

        # Format Volume Profile HVN/LVN
        hvn_text = ", ".join(
            f"${n['price']:.2f} ({n['volume']:.0f} vol)" for n in volume_profile.get("hvn", [])
        ) or "N/A"

        lvn_text = ", ".join(
            f"${n['price']:.2f} ({n['volume']:.0f} vol)" for n in volume_profile.get("lvn", [])
        ) or "N/A"

        # Format delta by minute
        delta_by_min = order_flow.get("delta_by_minute", [])
        delta_min_text = " → ".join(f"{d:+.0f}" for d in delta_by_min) if delta_by_min else "N/A"

        # Bid/Ask wall data
        bid_wall = dom_data.get("bid_wall", {})
        ask_wall = dom_data.get("ask_wall", {})

        return ANALYSIS_PROMPT.format(
            symbol=symbol,
            timeframe=timeframe,
            current_price=indicators.get("current_price", "N/A"),
            previous_close=indicators.get("previous_close", "N/A"),
            trend=indicators.get("trend", "UNKNOWN"),
            # DOM
            dom_imbalance=dom_data.get("imbalance", "N/A"),
            dom_dominant_side=dom_data.get("dominant_side", "N/A"),
            dom_bid_total=dom_data.get("bid_total_volume", 0),
            dom_ask_total=dom_data.get("ask_total_volume", 0),
            dom_bid_wall_price=bid_wall.get("price", 0),
            dom_bid_wall_vol=bid_wall.get("volume", 0),
            dom_ask_wall_price=ask_wall.get("price", 0),
            dom_ask_wall_vol=ask_wall.get("volume", 0),
            dom_bid_levels=dom_bid_lines,
            dom_ask_levels=dom_ask_lines,
            # Order Flow
            of_buy_vol=order_flow.get("buy_volume", 0),
            of_sell_vol=order_flow.get("sell_volume", 0),
            of_buy_pct=order_flow.get("buy_pct", 50),
            of_sell_pct=order_flow.get("sell_pct", 50),
            of_delta=order_flow.get("delta", 0),
            of_delta_pct=order_flow.get("delta_pct", 0),
            of_aggressor=order_flow.get("aggressor", "N/A"),
            of_delta_accel="⚡ YES" if order_flow.get("delta_accelerating", False) else "No",
            of_absorption="🔴 YES — REVERSAL WARNING" if order_flow.get("absorption_detected", False) else "No",
            of_tick_count=order_flow.get("tick_count", 0),
            of_delta_by_min=delta_min_text,
            # Volume Profile
            vp_bars=volume_profile.get("bars_analyzed", 0),
            vp_poc_price=volume_profile.get("poc_price", 0),
            vp_poc_vol=volume_profile.get("poc_volume", 0),
            vp_vah=volume_profile.get("vah", 0),
            vp_val=volume_profile.get("val", 0),
            vp_price_position=volume_profile.get("price_vs_value_area", "N/A"),
            vp_hvn=hvn_text,
            vp_lvn=lvn_text,
            # Technical indicators
            rsi_14=indicators.get("rsi_14", "N/A"),
            macd_line=macd_data.get("line", "N/A"),
            macd_signal=macd_data.get("signal", "N/A"),
            macd_histogram=macd_data.get("histogram", "N/A"),
            atr_14=indicators.get("atr_14", "N/A"),
            ema_9=indicators.get("ema_9", "N/A"),
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
            volume_spike="⚡ SPIKE" if indicators.get("volume_spike", False) else "Normal",
            momentum_5=indicators.get("momentum_5", "N/A"),
            candle_body_ratio=indicators.get("candle_body_ratio", "N/A"),
            last_5_candles=candles_text,
            open_positions=positions_text,
            balance=account_info.get("balance", 0),
            daily_pnl=daily_pnl,
        )

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
