import json
import os
import threading
from typing import Any, Dict
from config import SETTINGS_FILE, DEFAULT_LOGIN_LINK, DEFAULT_CLOSING_MSG

# Thread lock for safe concurrent file read/writes
_db_lock = threading.Lock()

# Default Base Configuration
DEFAULT_SETTINGS: Dict[str, Any] = {
    "target_channel": "@webdealx",       # Public username or Private channel ID (-100xxxx)
    "num_sessions": 2,                   # Default: 2 sessions per day
    "session_timings": ["14:00", "19:00"], # 24-hour IST format (e.g., 02:00 PM, 07:00 PM)
    "trades_per_session": 5,             # No. of trades in each session
    "login_link": DEFAULT_LOGIN_LINK,    # Broker login / registration link (Sent 10 mins before)
    "closing_message": DEFAULT_CLOSING_MSG, # Testimonial / review closing text
    "is_bot_active": True                # Master switch for signal automation
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
                # Ensure all default keys exist
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


def save_multiple_settings(updates: Dict[str, Any]) -> None:
    """Updates multiple settings at once and writes to disk."""
    settings = get_all_settings()
    with _db_lock:
        settings.update(updates)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)


# Initialize database file on import
initialize_db()