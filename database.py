import json
import os
import threading
from typing import Any, Dict, List
from config import (
    SETTINGS_FILE, 
    DEFAULT_LOGIN_LINK, 
    DEFAULT_EXPIRY_TEXT,
    DEFAULT_INVESTMENT_TEXT,
    DEFAULT_CLOSING_MSG_1, 
    DEFAULT_CLOSING_MSG_2, 
    DEFAULT_CLOSING_MSG_3,
    ALL_OTC_PAIRS
)

# Thread lock for safe concurrent file read/writes
_db_lock = threading.Lock()

# Default Selected Pairs
DEFAULT_SELECTED_PAIRS = [p["symbol"] for p in ALL_OTC_PAIRS[:7]]

# Default Base Configuration
DEFAULT_SETTINGS: Dict[str, Any] = {
    "target_channels": ["@webdealx"],
    "selected_pairs": DEFAULT_SELECTED_PAIRS,
    "num_sessions": 2,
    "session_timings": ["14:00", "19:00"],
    "trades_per_session": 5,
    "login_link": DEFAULT_LOGIN_LINK,
    "expiry_text": DEFAULT_EXPIRY_TEXT,          # Dynamic Expiry display text
    "investment_text": DEFAULT_INVESTMENT_TEXT,  # Dynamic Investment display text
    "closing_msg_1": DEFAULT_CLOSING_MSG_1,
    "closing_msg_2": DEFAULT_CLOSING_MSG_2,
    "closing_msg_3": DEFAULT_CLOSING_MSG_3,
    "reverse_strategy": True,                    # Invert signals (BUY -> SELL, SELL -> BUY)
    "is_bot_active": True                        # Master Session ON/OFF switch
}


def initialize_db() -> None:
    """Creates the settings JSON file if it does not already exist."""
    with _db_lock:
        if not os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SETTINGS, f, indent=4, ensure_ascii=False)


def get_all_settings() -> Dict[str, Any]:
    """Retrieves all current settings from persistent storage."""
    initialize_db()
    with _db_lock:
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                
                # Migrations and backward compatibility
                if "target_channel" in data and "target_channels" not in data:
                    data["target_channels"] = [data["target_channel"]]
                if "closing_message" in data and "closing_msg_2" not in data:
                    data["closing_msg_2"] = data["closing_message"]
                
                for k, v in DEFAULT_SETTINGS.items():
                    if k not in data:
                        data[k] = v
                return data
        except Exception:
            return DEFAULT_SETTINGS.copy()


def get_setting(key: str, default: Any = None) -> Any:
    """Gets a specific configuration setting by key."""
    settings = get_all_settings()
    return settings.get(key, default)


def update_setting(key: str, value: Any) -> None:
    """Updates and saves a specific configuration setting."""
    settings = get_all_settings()
    with _db_lock:
        settings[key] = value
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)


def get_channels() -> List[str]:
    """Returns the list of all configured target channels."""
    channels = get_setting("target_channels", ["@webdealx"])
    if isinstance(channels, str):
        return [channels]
    return list(channels)


def add_channel(channel_id_or_username: str) -> bool:
    """Adds a new channel to the target channels list."""
    ch = channel_id_or_username.strip()
    channels = get_channels()
    if ch not in channels:
        channels.append(ch)
        update_setting("target_channels", channels)
        return True
    return False


def remove_channel(channel_id_or_username: str) -> bool:
    """Removes a channel from the target channels list."""
    ch = channel_id_or_username.strip()
    channels = get_channels()
    if ch in channels:
        channels.remove(ch)
        update_setting("target_channels", channels)
        return True
    return False


def get_selected_pairs() -> List[str]:
    """Returns list of symbols currently selected by the Admin."""
    pairs = get_setting("selected_pairs", DEFAULT_SELECTED_PAIRS)
    if not pairs:
        return DEFAULT_SELECTED_PAIRS
    return list(pairs)


def toggle_pair_selection(symbol: str) -> bool:
    """Toggles a pair's selection state."""
    selected = get_selected_pairs()
    if symbol in selected:
        if len(selected) > 1:
            selected.remove(symbol)
            is_now_selected = False
        else:
            return True
    else:
        selected.append(symbol)
        is_now_selected = True
    update_setting("selected_pairs", selected)
    return is_now_selected


def is_pair_selected(symbol: str) -> bool:
    """Checks if a pair is in the active selected pairs list."""
    return symbol in get_selected_pairs()


# Initialize database file on import
initialize_db()
