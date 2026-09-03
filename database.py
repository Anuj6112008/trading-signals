import json
import os
import threading
from typing import Any, Dict, List
from config import SETTINGS_FILE, DEFAULT_LOGIN_LINK, DEFAULT_CLOSING_MSG

# Thread lock for safe concurrent file read/writes
_db_lock = threading.Lock()

# Default Base Configuration with Multi-Channel Support
DEFAULT_SETTINGS: Dict[str, Any] = {
    "target_channels": ["@webdealx"],     # List of Public (@username) or Private (-100xxxx) channels
    "num_sessions": 2,                     # Default: 2 sessions per day
    "session_timings": ["14:00", "19:00"], # 24-hour IST format (e.g. 14:00, 19:00)
    "trades_per_session": 5,               # No. of trades in each session
    "login_link": DEFAULT_LOGIN_LINK,      # Broker login / registration link
    "closing_message": DEFAULT_CLOSING_MSG, # Testimonial / review closing text
    "is_bot_active": True                  # Master switch for automation
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
                
                # Backward compatibility: Convert single channel to list if needed
                if "target_channel" in data and "target_channels" not in data:
                    data["target_channels"] = [data["target_channel"]]
                
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


# Initialize database file on import
initialize_db()
