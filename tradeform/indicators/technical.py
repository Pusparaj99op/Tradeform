"""
Technical indicators module.
Pure Python/NumPy implementations — no TA-Lib dependency.
"""

import numpy as np
import pandas as pd
from typing import Dict, Any, Optional


def sma(data: np.ndarray, period: int) -> np.ndarray:
    """Simple Moving Average."""
    if len(data) < period:
        return np.full_like(data, np.nan, dtype=float)
    result = np.full_like(data, np.nan, dtype=float)
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1 : i + 1])
    return result


def ema(data: np.ndarray, period: int) -> np.ndarray:
    """Exponential Moving Average."""
    if len(data) < period:
        return np.full_like(data, np.nan, dtype=float)
    result = np.full_like(data, np.nan, dtype=float)
    multiplier = 2.0 / (period + 1)
    # Seed with SMA
    result[period - 1] = np.mean(data[:period])
    for i in range(period, len(data)):
        result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    if len(close) < period + 1:
        return np.full_like(close, np.nan, dtype=float)

    delta = np.diff(close)
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    result = np.full(len(close), np.nan, dtype=float)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    if avg_loss == 0:
        result[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        result[period] = 100.0 - (100.0 / (1.0 + rs))

    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            result[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return result


def macd(
    close: np.ndarray,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple:
    """
    MACD indicator.
    Returns: (macd_line, signal_line, histogram)
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line[~np.isnan(macd_line)], signal)

    # Pad signal line to match original length
    pad_size = len(close) - len(signal_line)
    signal_padded = np.concatenate([np.full(pad_size, np.nan), signal_line])
    histogram = macd_line - signal_padded

    return macd_line, signal_padded, histogram


def atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Average True Range."""
    if len(close) < 2:
        return np.full_like(close, np.nan, dtype=float)

    # True Range
    tr = np.zeros(len(close))
    tr[0] = high[0] - low[0]
    for i in range(1, len(close)):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ATR using EMA-style smoothing
    result = np.full_like(close, np.nan, dtype=float)
    if len(tr) < period:
        return result

    result[period - 1] = np.mean(tr[:period])
    for i in range(period, len(tr)):
        result[i] = (result[i - 1] * (period - 1) + tr[i]) / period

    return result


def bollinger_bands(
    close: np.ndarray,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple:
    """
    Bollinger Bands.
    Returns: (upper, middle, lower)
    """
    middle = sma(close, period)
    result_upper = np.full_like(close, np.nan, dtype=float)
    result_lower = np.full_like(close, np.nan, dtype=float)

    for i in range(period - 1, len(close)):
        std = np.std(close[i - period + 1 : i + 1])
        result_upper[i] = middle[i] + std_dev * std
        result_lower[i] = middle[i] - std_dev * std

    return result_upper, middle, result_lower


def support_resistance(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    lookback: int = 50,
) -> Dict[str, float]:
    """
    Simple support/resistance based on recent highs/lows.
    Returns dict with support and resistance levels.
    """
    recent_high = high[-lookback:]
    recent_low = low[-lookback:]

    return {
        "resistance_1": float(np.max(recent_high)),
        "resistance_2": float(np.percentile(recent_high, 75)),
        "support_1": float(np.min(recent_low)),
        "support_2": float(np.percentile(recent_low, 25)),
        "pivot": float((np.max(recent_high) + np.min(recent_low) + close[-1]) / 3),
    }


def compute_all_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Compute all technical indicators from OHLCV DataFrame.
    Returns a structured dict ready for AI prompt injection.
    
    Expects DataFrame with columns: open, high, low, close, tick_volume
    """
    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    volume = df["tick_volume"].values.astype(float)

    # Compute indicators
    rsi_14 = rsi(close, 14)
    macd_line, signal_line, histogram = macd(close)
    atr_14 = atr(high, low, close, 14)
    ema_20 = ema(close, 20)
    ema_50 = ema(close, 50)
    ema_200 = ema(close, 200)
    bb_upper, bb_middle, bb_lower = bollinger_bands(close)
    sr_levels = support_resistance(high, low, close)

    # Get latest values (non-NaN)
    def latest(arr):
        valid = arr[~np.isnan(arr)]
        return round(float(valid[-1]), 5) if len(valid) > 0 else None

    result = {
        "current_price": round(float(close[-1]), 5),
        "previous_close": round(float(close[-2]), 5) if len(close) > 1 else None,
        "rsi_14": round(latest(rsi_14), 2) if latest(rsi_14) else None,
        "macd": {
            "line": latest(macd_line),
            "signal": latest(signal_line),
            "histogram": latest(histogram),
        },
        "atr_14": latest(atr_14),
        "ema_20": latest(ema_20),
        "ema_50": latest(ema_50),
        "ema_200": latest(ema_200),
        "bollinger": {
            "upper": latest(bb_upper),
            "middle": latest(bb_middle),
            "lower": latest(bb_lower),
        },
        "support_resistance": sr_levels,
        "volume_avg_20": round(float(np.mean(volume[-20:])), 0) if len(volume) >= 20 else None,
        "volume_current": float(volume[-1]),
        "trend": _determine_trend(close, ema_20, ema_50),
        "last_5_candles": [
            {
                "open": round(float(df["open"].iloc[i]), 5),
                "high": round(float(df["high"].iloc[i]), 5),
                "low": round(float(df["low"].iloc[i]), 5),
                "close": round(float(df["close"].iloc[i]), 5),
            }
            for i in range(-5, 0)
        ],
    }

    return result


def _determine_trend(
    close: np.ndarray,
    ema_20: np.ndarray,
    ema_50: np.ndarray,
) -> str:
    """Determine the current trend direction."""
    price = close[-1]
    e20 = ema_20[~np.isnan(ema_20)]
    e50 = ema_50[~np.isnan(ema_50)]

    if len(e20) == 0 or len(e50) == 0:
        return "UNKNOWN"

    e20_val = e20[-1]
    e50_val = e50[-1]

    if price > e20_val > e50_val:
        return "STRONG_BULLISH"
    elif price > e20_val:
        return "BULLISH"
    elif price < e20_val < e50_val:
        return "STRONG_BEARISH"
    elif price < e20_val:
        return "BEARISH"
    else:
        return "NEUTRAL"
