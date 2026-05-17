"""
Order Flow, Volume Profile, and Depth of Market (DOM) analysis.
Institutional-grade market microstructure tools for gold scalping.
"""

import numpy as np
import pandas as pd
import MetaTrader5 as mt5
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple


# ── Depth of Market (DOM / Level 2) ──────────────────────────

def get_dom_snapshot(symbol: str, depth: int = 20) -> Dict[str, Any]:
    """
    Get the current Depth of Market (Level 2 order book).
    Shows pending buy/sell limit orders at each price level.

    Returns:
        Dict with bid_levels, ask_levels, bid_total, ask_total,
        imbalance ratio, and dominant side.
    """
    # Subscribe to DOM (must be called before market_book_get)
    if not mt5.market_book_add(symbol):
        return _empty_dom()

    book = mt5.market_book_get(symbol)
    if book is None or len(book) == 0:
        mt5.market_book_release(symbol)
        return _empty_dom()

    bids = []
    asks = []

    for entry in book:
        item = entry._asdict() if hasattr(entry, '_asdict') else {
            "type": entry.type, "price": entry.price, "volume": entry.volume
        }

        if item.get("type") == mt5.BOOK_TYPE_SELL or item.get("type") == mt5.BOOK_TYPE_SELL_MARKET:
            asks.append({
                "price": round(float(item["price"]), 2),
                "volume": int(item.get("volume", 0)),
            })
        elif item.get("type") == mt5.BOOK_TYPE_BUY or item.get("type") == mt5.BOOK_TYPE_BUY_MARKET:
            bids.append({
                "price": round(float(item["price"]), 2),
                "volume": int(item.get("volume", 0)),
            })

    # Release DOM subscription
    mt5.market_book_release(symbol)

    # Sort: bids descending (highest first), asks ascending (lowest first)
    bids.sort(key=lambda x: x["price"], reverse=True)
    asks.sort(key=lambda x: x["price"])

    # Limit to requested depth
    bids = bids[:depth]
    asks = asks[:depth]

    bid_total = sum(b["volume"] for b in bids)
    ask_total = sum(a["volume"] for a in asks)
    total = bid_total + ask_total

    # Imbalance: positive = more buyers (bullish), negative = more sellers (bearish)
    if total > 0:
        imbalance = round((bid_total - ask_total) / total, 4)
    else:
        imbalance = 0.0

    # Find largest bid/ask walls
    biggest_bid = max(bids, key=lambda x: x["volume"]) if bids else {"price": 0, "volume": 0}
    biggest_ask = max(asks, key=lambda x: x["volume"]) if asks else {"price": 0, "volume": 0}

    return {
        "bid_levels": bids[:5],   # Top 5 bid levels for prompt
        "ask_levels": asks[:5],   # Top 5 ask levels for prompt
        "bid_total_volume": bid_total,
        "ask_total_volume": ask_total,
        "imbalance": imbalance,
        "dominant_side": "BUYERS" if imbalance > 0.1 else ("SELLERS" if imbalance < -0.1 else "BALANCED"),
        "bid_wall": biggest_bid,  # Largest support level
        "ask_wall": biggest_ask,  # Largest resistance level
        "depth_levels": len(bids) + len(asks),
    }


def _empty_dom() -> Dict[str, Any]:
    """Return empty DOM data when unavailable."""
    return {
        "bid_levels": [],
        "ask_levels": [],
        "bid_total_volume": 0,
        "ask_total_volume": 0,
        "imbalance": 0.0,
        "dominant_side": "UNAVAILABLE",
        "bid_wall": {"price": 0, "volume": 0},
        "ask_wall": {"price": 0, "volume": 0},
        "depth_levels": 0,
    }


# ── Order Flow (Tick-by-Tick Analysis) ───────────────────────

def compute_order_flow(symbol: str, seconds: int = 300) -> Dict[str, Any]:
    """
    Analyze recent tick-by-tick data to compute order flow metrics.
    Uses MT5 tick flags to classify trades as aggressive buys or sells.

    Args:
        symbol: Trading symbol
        seconds: How many seconds of ticks to analyze (default: 5 minutes)

    Returns:
        Dict with delta, cumulative delta, buy/sell volume,
        aggressor side, and absorption detection.
    """
    date_to = datetime.now()
    date_from = date_to - timedelta(seconds=seconds)

    # Fetch ticks with trade info
    ticks = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_TRADE)

    if ticks is None or len(ticks) == 0:
        # Fallback: try all ticks
        ticks = mt5.copy_ticks_range(symbol, date_from, date_to, mt5.COPY_TICKS_ALL)

    if ticks is None or len(ticks) == 0:
        return _empty_order_flow()

    df = pd.DataFrame(ticks)

    # Classify ticks using flags
    # MT5 flags: TICK_FLAG_BUY = 8, TICK_FLAG_SELL = 16
    buy_mask = (df["flags"] & 8) > 0    # TICK_FLAG_BUY
    sell_mask = (df["flags"] & 16) > 0   # TICK_FLAG_SELL

    # Volume from classified ticks
    if "volume_real" in df.columns:
        vol_col = "volume_real"
    elif "volume" in df.columns:
        vol_col = "volume"
    else:
        vol_col = None

    if vol_col and df[vol_col].sum() > 0:
        buy_volume = float(df.loc[buy_mask, vol_col].sum())
        sell_volume = float(df.loc[sell_mask, vol_col].sum())
    else:
        # Fallback: count ticks instead of volume
        buy_volume = float(buy_mask.sum())
        sell_volume = float(sell_mask.sum())

    total_volume = buy_volume + sell_volume
    delta = buy_volume - sell_volume

    # Cumulative delta over time windows
    # Split ticks into 1-minute buckets for delta progression
    if len(df) > 0 and "time" in df.columns:
        df["time_dt"] = pd.to_datetime(df["time"], unit="s")
        df["minute"] = df["time_dt"].dt.floor("min")

        delta_by_minute = []
        for minute, group in df.groupby("minute"):
            m_buy = (group["flags"] & 8) > 0
            m_sell = (group["flags"] & 16) > 0
            if vol_col and group[vol_col].sum() > 0:
                m_delta = float(group.loc[m_buy, vol_col].sum() - group.loc[m_sell, vol_col].sum())
            else:
                m_delta = float(m_buy.sum() - m_sell.sum())
            delta_by_minute.append(m_delta)

        # Delta trend: is cumulative delta increasing or decreasing?
        if len(delta_by_minute) >= 2:
            recent_delta = sum(delta_by_minute[-2:])
            older_delta = sum(delta_by_minute[:-2]) if len(delta_by_minute) > 2 else 0
            delta_accelerating = recent_delta > older_delta
        else:
            delta_accelerating = False
    else:
        delta_by_minute = []
        delta_accelerating = False

    # Aggressor detection
    if total_volume > 0:
        buy_pct = buy_volume / total_volume
        sell_pct = sell_volume / total_volume
    else:
        buy_pct = 0.5
        sell_pct = 0.5

    if buy_pct > 0.6:
        aggressor = "AGGRESSIVE_BUYERS"
    elif sell_pct > 0.6:
        aggressor = "AGGRESSIVE_SELLERS"
    else:
        aggressor = "MIXED"

    # Absorption detection: high volume but no price movement = institutional absorption
    if len(df) > 10:
        price_range = float(df["ask"].max() - df["bid"].min()) if "ask" in df.columns and "bid" in df.columns else 0
        tick_count = len(df)
        absorption = price_range < 1.0 and tick_count > 100  # Gold: < $1 move with 100+ ticks
    else:
        absorption = False

    return {
        "buy_volume": round(buy_volume, 2),
        "sell_volume": round(sell_volume, 2),
        "total_volume": round(total_volume, 2),
        "delta": round(delta, 2),
        "delta_pct": round((delta / total_volume * 100), 1) if total_volume > 0 else 0,
        "buy_pct": round(buy_pct * 100, 1),
        "sell_pct": round(sell_pct * 100, 1),
        "aggressor": aggressor,
        "delta_accelerating": delta_accelerating,
        "absorption_detected": absorption,
        "tick_count": len(df),
        "delta_by_minute": delta_by_minute[-5:] if delta_by_minute else [],
    }


def _empty_order_flow() -> Dict[str, Any]:
    """Return empty order flow data when unavailable."""
    return {
        "buy_volume": 0,
        "sell_volume": 0,
        "total_volume": 0,
        "delta": 0,
        "delta_pct": 0,
        "buy_pct": 50,
        "sell_pct": 50,
        "aggressor": "UNAVAILABLE",
        "delta_accelerating": False,
        "absorption_detected": False,
        "tick_count": 0,
        "delta_by_minute": [],
    }


# ── Volume Profile ──────────────────────────────────────────

def compute_volume_profile(
    symbol: str,
    timeframe_str: str = "M1",
    bars: int = 120,
    num_levels: int = 30,
) -> Dict[str, Any]:
    """
    Compute Volume Profile from recent bars.
    Distributes volume across price levels to find:
    - POC (Point of Control) — highest volume price
    - VAH (Value Area High) — upper 70% of volume
    - VAL (Value Area Low) — lower 70% of volume
    - HVN (High Volume Nodes) — institutional accumulation zones
    - LVN (Low Volume Nodes) — potential breakout levels

    Args:
        symbol: Trading symbol
        timeframe_str: Timeframe for bars
        bars: Number of bars to analyze
        num_levels: Price levels for the profile histogram
    """
    from tradeform.mt5.connection import TIMEFRAME_MAP

    tf = TIMEFRAME_MAP.get(timeframe_str)
    if tf is None:
        return _empty_volume_profile()

    rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars)
    if rates is None or len(rates) < 20:
        return _empty_volume_profile()

    df = pd.DataFrame(rates)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    close = df["close"].values.astype(float)
    volume = df["tick_volume"].values.astype(float)

    # Price range for the profile
    price_min = float(np.min(low))
    price_max = float(np.max(high))
    price_range = price_max - price_min

    if price_range <= 0:
        return _empty_volume_profile()

    # Create price levels
    levels = np.linspace(price_min, price_max, num_levels + 1)
    level_centers = (levels[:-1] + levels[1:]) / 2
    level_volumes = np.zeros(num_levels)

    # Distribute volume across price levels using TPO-style approach
    # Each bar's volume is distributed across all levels it touches
    for i in range(len(df)):
        bar_low = low[i]
        bar_high = high[i]
        bar_vol = volume[i]

        # Find which levels this bar covers
        for j in range(num_levels):
            if levels[j + 1] >= bar_low and levels[j] <= bar_high:
                # Count how much of the bar overlaps this level
                overlap_low = max(levels[j], bar_low)
                overlap_high = min(levels[j + 1], bar_high)
                bar_range = bar_high - bar_low
                if bar_range > 0:
                    proportion = (overlap_high - overlap_low) / bar_range
                else:
                    proportion = 1.0
                level_volumes[j] += bar_vol * proportion

    # Find POC (Point of Control) — highest volume level
    poc_idx = int(np.argmax(level_volumes))
    poc_price = round(float(level_centers[poc_idx]), 2)
    poc_volume = round(float(level_volumes[poc_idx]), 0)

    # Calculate Value Area (70% of total volume around POC)
    total_vol = float(np.sum(level_volumes))
    value_area_vol = total_vol * 0.70

    # Expand from POC outward until 70% is captured
    va_indices = {poc_idx}
    accumulated = float(level_volumes[poc_idx])
    lower_idx = poc_idx - 1
    upper_idx = poc_idx + 1

    while accumulated < value_area_vol and (lower_idx >= 0 or upper_idx < num_levels):
        lower_vol = float(level_volumes[lower_idx]) if lower_idx >= 0 else 0
        upper_vol = float(level_volumes[upper_idx]) if upper_idx < num_levels else 0

        if lower_vol >= upper_vol and lower_idx >= 0:
            va_indices.add(lower_idx)
            accumulated += lower_vol
            lower_idx -= 1
        elif upper_idx < num_levels:
            va_indices.add(upper_idx)
            accumulated += upper_vol
            upper_idx += 1
        else:
            break

    vah_price = round(float(level_centers[max(va_indices)]), 2)
    val_price = round(float(level_centers[min(va_indices)]), 2)

    # Find High Volume Nodes (top 3 volume levels)
    top_indices = np.argsort(level_volumes)[-3:][::-1]
    hvn = [
        {"price": round(float(level_centers[i]), 2), "volume": round(float(level_volumes[i]), 0)}
        for i in top_indices
    ]

    # Find Low Volume Nodes (bottom 3, non-zero, as potential breakout zones)
    nonzero_mask = level_volumes > 0
    if np.sum(nonzero_mask) > 3:
        nonzero_indices = np.where(nonzero_mask)[0]
        sorted_by_vol = nonzero_indices[np.argsort(level_volumes[nonzero_indices])]
        lvn = [
            {"price": round(float(level_centers[i]), 2), "volume": round(float(level_volumes[i]), 0)}
            for i in sorted_by_vol[:3]
        ]
    else:
        lvn = []

    # Price position relative to value area
    current_price = float(close[-1])
    if current_price > vah_price:
        price_vs_va = "ABOVE_VALUE"     # Potential to return to VA or breakout
    elif current_price < val_price:
        price_vs_va = "BELOW_VALUE"     # Potential to return to VA or breakdown
    else:
        price_vs_va = "INSIDE_VALUE"    # Trading within fair value

    return {
        "poc_price": poc_price,
        "poc_volume": poc_volume,
        "vah": vah_price,
        "val": val_price,
        "price_vs_value_area": price_vs_va,
        "hvn": hvn,
        "lvn": lvn,
        "total_profile_volume": round(total_vol, 0),
        "bars_analyzed": len(df),
    }


def _empty_volume_profile() -> Dict[str, Any]:
    """Return empty volume profile when unavailable."""
    return {
        "poc_price": 0,
        "poc_volume": 0,
        "vah": 0,
        "val": 0,
        "price_vs_value_area": "UNAVAILABLE",
        "hvn": [],
        "lvn": [],
        "total_profile_volume": 0,
        "bars_analyzed": 0,
    }
