from typing import Optional, Tuple, List, Dict, Any
import pandas as pd
from market_feed import get_asset_candles, get_latest_price
from config import ALL_OTC_PAIRS
from database import get_selected_pairs, get_setting

# Track last sent pair to enforce fair rotation
_last_sent_symbol: str = ""
_rotation_index: int = 0


def evaluate_micro_direction(symbol: str) -> Tuple[Optional[str], Optional[str], float]:
    """
    Evaluates candle buffer and applies the Reverse Strategy Inversion:
    - Raw Bullish Indicator -> Inverted to 'PUT' (SELL)
    - Raw Bearish Indicator -> Inverted to 'CALL' (BUY)
    """
    data = get_asset_candles(symbol)
    current_price = get_latest_price(symbol)
    is_reverse = get_setting("reverse_strategy", True)

    if len(data) < 3:
        if current_price > 0:
            raw_dir = "CALL"
            final_dir = "PUT" if is_reverse else raw_dir
            return final_dir, f"Momentum [{current_price}] (Inverted)", current_price
        return None, None, 0.0

    df = pd.DataFrame(data)
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)

    # Fast EMA & RSI Indicators
    df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(5).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(5).mean()
    df['rsi'] = 100 - (100 / (1 + (gain / (loss + 1e-9))))

    c0 = df.iloc[-1]
    latest_price = float(c0['close'])
    rsi_val = float(c0['rsi']) if not pd.isna(c0['rsi']) else 50.0

    # 1. Raw Market Direction Evaluation
    if c0['close'] > c0['open'] and (c0['close'] >= c0['ema5'] or rsi_val >= 48):
        raw_direction = "CALL"
        lead_info = f"Bullish Flow + RSI [{round(rsi_val, 1)}]"
    elif c0['close'] < c0['open'] and (c0['close'] <= c0['ema5'] or rsi_val <= 52):
        raw_direction = "PUT"
        lead_info = f"Bearish Flow + RSI [{round(rsi_val, 1)}]"
    elif rsi_val >= 50:
        raw_direction = "CALL"
        lead_info = f"RSI Bullish [{round(rsi_val, 1)}]"
    else:
        raw_direction = "PUT"
        lead_info = f"RSI Bearish [{round(rsi_val, 1)}]"

    # 2. Apply Reverse Strategy Inversion
    if is_reverse:
        final_direction = "PUT" if raw_direction == "CALL" else "CALL"
        lead_text = f"{lead_info} (Reverse: {raw_direction} -> {final_direction})"
    else:
        final_direction = raw_direction
        lead_text = lead_info

    return final_direction, lead_text, latest_price


def find_next_trading_opportunity() -> Optional[Tuple[Dict[str, Any], str, str, float]]:
    """
    Filters watchlist to ONLY Admin-Selected pairs and rotates fairly among them.
    Returns: (pair_metadata, final_inverted_direction, lead_signal, entry_price) or None
    """
    global _last_sent_symbol, _rotation_index

    # 1. Get Selected Pairs from Admin Database
    selected_symbols = get_selected_pairs()
    active_watchlist = [item for item in ALL_OTC_PAIRS if item["symbol"] in selected_symbols]

    if not active_watchlist:
        active_watchlist = ALL_OTC_PAIRS[:5]  # Safe fallback

    # 2. Fair Rotation across Selected Pairs
    if _rotation_index >= len(active_watchlist):
        _rotation_index = 0

    rotated_list = active_watchlist[_rotation_index:] + active_watchlist[:_rotation_index]
    _rotation_index = (_rotation_index + 1) % len(active_watchlist)

    for item in rotated_list:
        sym = item["symbol"]

        # Prevent immediate repetition if multiple pairs are selected
        if sym == _last_sent_symbol and len(active_watchlist) > 1:
            continue

        direction, lead, entry_price = evaluate_micro_direction(sym)
        if direction and entry_price > 0:
            _last_sent_symbol = sym
            return item, direction, lead, entry_price

    return None
