"""
Configuration loader and validator for Tradeform.
Reads config.yaml and provides typed access to all settings.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class MT5Config:
    """MetaTrader 5 connection settings."""
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = ""


@dataclass
class OllamaConfig:
    """Ollama LLM settings."""
    host: str = "http://localhost:11434"
    model: str = "llama3.2"
    temperature: float = 0.3
    analysis_interval_minutes: int = 5


@dataclass
class TradingConfig:
    """Trading behavior settings."""
    symbols: List[str] = field(default_factory=lambda: ["EURUSD", "GBPUSD", "USDJPY"])
    timeframe: str = "M15"
    mode: str = "confirmation"  # "auto" or "confirmation"


@dataclass
class RiskConfig:
    """Risk management settings."""
    max_risk_per_trade_pct: float = 1.0
    max_daily_drawdown_pct: float = 3.0
    max_positions: int = 3
    max_lot_size: float = 0.5
    default_sl_atr_multiplier: float = 1.5
    default_tp_atr_multiplier: float = 2.5


@dataclass
class AppConfig:
    """Root configuration container."""
    mt5: MT5Config = field(default_factory=MT5Config)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    Load configuration from YAML file.
    Falls back to defaults if file not found.
    """
    config = AppConfig()

    # Resolve path relative to project root
    if not os.path.isabs(config_path):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(project_root, config_path)

    if not os.path.exists(config_path):
        return config

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        return config

    # Parse MT5 config
    if "mt5" in raw:
        mt5_raw = raw["mt5"]
        config.mt5 = MT5Config(
            login=int(mt5_raw.get("login", 0)),
            password=str(mt5_raw.get("password", "")),
            server=str(mt5_raw.get("server", "")),
            path=str(mt5_raw.get("path", "")),
        )

    # Parse Ollama config
    if "ollama" in raw:
        ol_raw = raw["ollama"]
        config.ollama = OllamaConfig(
            host=str(ol_raw.get("host", "http://localhost:11434")),
            model=str(ol_raw.get("model", "llama3.2")),
            temperature=float(ol_raw.get("temperature", 0.3)),
            analysis_interval_minutes=int(ol_raw.get("analysis_interval_minutes", 5)),
        )

    # Parse Trading config
    if "trading" in raw:
        tr_raw = raw["trading"]
        config.trading = TradingConfig(
            symbols=list(tr_raw.get("symbols", ["EURUSD"])),
            timeframe=str(tr_raw.get("timeframe", "M15")),
            mode=str(tr_raw.get("mode", "confirmation")),
        )

    # Parse Risk config
    if "risk" in raw:
        rk_raw = raw["risk"]
        config.risk = RiskConfig(
            max_risk_per_trade_pct=float(rk_raw.get("max_risk_per_trade_pct", 1.0)),
            max_daily_drawdown_pct=float(rk_raw.get("max_daily_drawdown_pct", 3.0)),
            max_positions=int(rk_raw.get("max_positions", 3)),
            max_lot_size=float(rk_raw.get("max_lot_size", 0.5)),
            default_sl_atr_multiplier=float(rk_raw.get("default_sl_atr_multiplier", 1.5)),
            default_tp_atr_multiplier=float(rk_raw.get("default_tp_atr_multiplier", 2.5)),
        )

    return config
