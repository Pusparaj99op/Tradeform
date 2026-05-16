"""
Risk management module.
Position sizing, drawdown guards, exposure limits, and kill switch.
"""

import MetaTrader5 as mt5
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from tradeform.config import RiskConfig


@dataclass
class RiskCheck:
    """Result of a risk validation check."""
    approved: bool
    reason: str = ""
    calculated_lot_size: float = 0.0
    risk_amount: float = 0.0


class RiskManager:
    """Validates trades against risk rules before execution."""

    def __init__(self, config: RiskConfig):
        self.config = config
        self._daily_pnl: float = 0.0
        self._daily_reset_date: str = ""
        self._killed: bool = False  # Kill switch state

    @property
    def is_killed(self) -> bool:
        return self._killed

    def kill_switch_on(self):
        """Activate kill switch — blocks all new trades."""
        self._killed = True

    def kill_switch_off(self):
        """Deactivate kill switch — resume trading."""
        self._killed = False

    def calculate_lot_size(
        self,
        balance: float,
        sl_distance_points: float,
        symbol_info: Dict[str, Any],
    ) -> float:
        """
        Calculate position size based on risk percentage.
        
        Args:
            balance: Account balance
            sl_distance_points: Stop loss distance in price points
            symbol_info: Symbol info dict from MT5 (needs trade_contract_size, point, volume_min, volume_max, volume_step)
        """
        if sl_distance_points <= 0:
            return symbol_info.get("volume_min", 0.01)

        risk_amount = balance * (self.config.max_risk_per_trade_pct / 100.0)

        # Calculate pip value
        contract_size = symbol_info.get("trade_contract_size", 100000)
        point = symbol_info.get("point", 0.00001)

        # Value per point per lot
        point_value = contract_size * point

        if point_value <= 0:
            return symbol_info.get("volume_min", 0.01)

        # Calculate lot size
        lot_size = risk_amount / (sl_distance_points * point_value / point)

        # Apply constraints
        vol_min = symbol_info.get("volume_min", 0.01)
        vol_max = min(
            symbol_info.get("volume_max", 100.0),
            self.config.max_lot_size,
        )
        vol_step = symbol_info.get("volume_step", 0.01)

        # Round to volume step
        lot_size = max(vol_min, min(lot_size, vol_max))
        lot_size = round(lot_size / vol_step) * vol_step
        lot_size = round(lot_size, 2)

        return lot_size

    def validate_trade(
        self,
        symbol: str,
        direction: str,
        volume: float,
        balance: float,
        equity: float,
        open_positions: List[Dict[str, Any]],
    ) -> RiskCheck:
        """
        Validate a trade against all risk rules.
        Returns RiskCheck with approval status and reason.
        """
        # Check kill switch
        if self._killed:
            return RiskCheck(
                approved=False,
                reason="🛑 Kill switch is active. No new trades allowed.",
            )

        # Check daily drawdown
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today

        daily_loss_limit = balance * (self.config.max_daily_drawdown_pct / 100.0)
        if self._daily_pnl < 0 and abs(self._daily_pnl) >= daily_loss_limit:
            return RiskCheck(
                approved=False,
                reason=f"⚠️ Daily drawdown limit reached ({self.config.max_daily_drawdown_pct}%). "
                       f"Loss today: ${abs(self._daily_pnl):.2f}",
            )

        # Check max positions
        current_count = len(open_positions)
        if current_count >= self.config.max_positions:
            return RiskCheck(
                approved=False,
                reason=f"⚠️ Max positions ({self.config.max_positions}) already open.",
            )

        # Check lot size limit
        if volume > self.config.max_lot_size:
            return RiskCheck(
                approved=False,
                reason=f"⚠️ Volume {volume} exceeds max lot size ({self.config.max_lot_size}).",
            )

        # Check margin (basic check — equity should be well above margin)
        if equity < balance * 0.5:
            return RiskCheck(
                approved=False,
                reason="⚠️ Equity is below 50% of balance. High margin usage.",
            )

        # Check for duplicate direction on same symbol
        for pos in open_positions:
            if pos.get("symbol") == symbol:
                pos_type = "BUY" if pos.get("type") == 0 else "SELL"
                if pos_type == direction:
                    return RiskCheck(
                        approved=False,
                        reason=f"⚠️ Already have a {direction} position on {symbol}.",
                    )

        return RiskCheck(
            approved=True,
            reason="✅ Trade passes all risk checks.",
            calculated_lot_size=volume,
        )

    def update_daily_pnl(self, pnl: float):
        """Update the running daily P/L tracker."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_reset_date != today:
            self._daily_pnl = 0.0
            self._daily_reset_date = today
        self._daily_pnl += pnl

    def get_risk_summary(
        self,
        balance: float,
        open_positions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Get a summary of current risk exposure."""
        total_exposure = sum(abs(p.get("volume", 0)) for p in open_positions)
        floating_pnl = sum(p.get("profit", 0) for p in open_positions)

        return {
            "kill_switch": self._killed,
            "daily_pnl": round(self._daily_pnl, 2),
            "daily_limit": round(balance * (self.config.max_daily_drawdown_pct / 100.0), 2),
            "daily_pnl_pct": round((self._daily_pnl / balance) * 100, 2) if balance > 0 else 0,
            "open_positions": len(open_positions),
            "max_positions": self.config.max_positions,
            "total_lots": round(total_exposure, 2),
            "max_lot_size": self.config.max_lot_size,
            "floating_pnl": round(floating_pnl, 2),
        }
