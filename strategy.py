from typing import Optional, Tuple, List, Dict, Any
import pandas as pd
from market_feed import get_asset_candles, get_latest_price
from config import TARGET_ASSETS

# Track last sent pair to enforce fair rotation across all 7 assets
_last_sent_symbol: str = ""
_rotation_index: int = 0


def evaluate_micro_direction(symbol: str) -> Tuple[Optional[str], Optional[str], float]:
    """
    Evaluates candle buffer for directional bias on 1M timeframe:
    - Symmetric 50/50 balance between BUY (CALL) and SELL (PUT)
    - Returns: (Direction 'CALL'/'PUT'/None, Lead Signal Description, Current Price)
    """
    data = get_asset_candles(symbol)
    current_price = get_latest_price(symbol)

    if len(data) < 3:
        if current_price > 0:
            return "CALL", f"Live Price Momentum [{current_price}]", current_price
        return None, None, 0.0

    df = pd.DataFrame(data)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)

    # Technical Indicators: EMA(5) & Fast RSI(7)
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(5).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(5).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    c0 = df.iloc[-1]
    latest_price = float(c0['close'])
    rsi_val = float(c0['rsi']) if not pd.isna(c0['rsi']) else 50.0

    # 🟢 SYMMETRIC BUY (CALL) SETUP: Green Candle + Bullish Bias
    if c0['close'] > c0['open'] and (c0['close'] >= c0['ema5'] or rsi_val >= 48):
        lead = f"Bullish Flow + RSI [{round(rsi_val, 1)}]"
        return "CALL", lead, latest_price

    # 🔴 SYMMETRIC SELL (PUT) SETUP: Red Candle + Bearish Bias
    elif c0['close'] < c0['open'] and (c0['close'] <= c0['ema5'] or rsi_val <= 52):
        lead = f"Bearish Flow + RSI [{round(rsi_val, 1)}]"
        return "PUT", lead, latest_price

    # Fallback Momentum Bias (If Doji / Equal Open-Close)
    elif rsi_val >= 50:
        return "CALL", f"RSI Bullish [{round(rsi_val, 1)}]", latest_price
    else:
        return "PUT", f"RSI Bearish [{round(rsi_val, 1)}]", latest_price


def find_next_trading_opportunity() -> Optional[Tuple[Dict[str, Any], str, str, float]]:
    """
    Scans the watchlist in round-robin rotated order to ensure no single pair repeats.
    Returns: (pair_metadata, direction, lead_signal, entry_price) or None
    """
    global _last_sent_symbol, _rotation_index

    # Rotate starting position so all 7 pairs get equal priority
    rotated_watchlist = TARGET_ASSETS[_rotation_index:] + TARGET_ASSETS[:_rotation_index]
    _rotation_index = (_rotation_index + 1) % len(TARGET_ASSETS)

    for item in rotated_watchlist:
        sym = item["symbol"]

        # Prevent immediate consecutive signal on the same pair
        if sym == _last_sent_symbol and len(TARGET_ASSETS) > 1:
            continue

        direction, lead, entry_price = evaluate_micro_direction(sym)
        if direction and entry_price > 0:
            _last_sent_symbol = sym
            return item, direction, lead, entry_price

    return None