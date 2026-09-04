import time
import threading
from typing import Dict, List, Optional
import requests
from config import ALL_OTC_PAIRS

# Shared In-Memory Real-Time Candlestick Storage for all 41 pairs
_feed_lock = threading.Lock()
candles_live: Dict[str, List[Dict[str, float]]] = {item["symbol"]: [] for item in ALL_OTC_PAIRS}
live_prices: Dict[str, float] = {item["symbol"]: 0.0 for item in ALL_OTC_PAIRS}
_is_streaming: bool = False


def fetch_all_candles() -> None:
    """Fetches real-time M1 historical and forming candles across all 41 OTC assets."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    }

    for item in ALL_OTC_PAIRS:
        sym = item["symbol"]
        q = item["query"]
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{q}?interval=1m&range=1d"
            res = session.get(url, headers=headers, timeout=4).json()
            result = res['chart']['result'][0]
            quotes = result['indicators']['quote'][0]
            timestamps = result['timestamp']

            candles: List[Dict[str, float]] = []
            for i in range(len(timestamps)):
                if quotes['close'][i] is not None:
                    candles.append({
                        "open": float(quotes['open'][i]),
                        "high": float(quotes['high'][i]),
                        "low": float(quotes['low'][i]),
                        "close": float(quotes['close'][i]),
                        "time": float(timestamps[i])
                    })

            if candles:
                with _feed_lock:
                    candles_live[sym] = candles[-30:]  # Keep latest 30 candles
                    live_prices[sym] = candles[-1]['close']
        except Exception:
            pass


def _background_feed_loop() -> None:
    """Continuously refreshes market quotes in background thread."""
    global _is_streaming
    _is_streaming = True
    while True:
        try:
            fetch_all_candles()
        except Exception:
            pass
        time.sleep(4)  # Safe 4-second poll interval to avoid rate limits


def start_market_feed() -> None:
    """Initializes the candle buffer and starts the live streaming daemon."""
    fetch_all_candles()
    t = threading.Thread(target=_background_feed_loop, daemon=True, name="MarketFeedWorker")
    t.start()


def get_asset_candles(symbol: str) -> List[Dict[str, float]]:
    """Thread-safe accessor for an asset's candle history."""
    with _feed_lock:
        return list(candles_live.get(symbol, []))


def get_latest_price(symbol: str) -> float:
    """Thread-safe accessor for an asset's latest price."""
    with _feed_lock:
        return float(live_prices.get(symbol, 0.0))


def is_feed_active() -> bool:
    """Checks if data buffers are loaded and streaming."""
    with _feed_lock:
        loaded = sum(len(v) for v in candles_live.values())
        return loaded >= 5
