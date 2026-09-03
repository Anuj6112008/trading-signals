import time
import sys
from datetime import datetime
import telebot

from config import BOT_TOKEN, IST, TARGET_ASSETS
from database import initialize_db, get_all_settings
from market_feed import start_market_feed, is_feed_active
from scheduler import start_scheduler
from admin_panel import register_admin_handlers


def print_banner() -> None:
    """Displays a clean launch banner with active configurations."""
    now_str = datetime.now(IST).strftime("%I:%M:%S %p IST | %d-%b-%Y")
    s = get_all_settings()
    timings = ", ".join(s.get("session_timings", []))

    print("=" * 70)
    print("🚀 POCKET OPTION MODULAR VIP SIGNAL ENGINE (PRODUCTION V2.0)")
    print(f"⏰ Launch Time: {now_str}")
    print(f"📢 Target Channel: {s.get('target_channel')}")
    print(f"⏰ Scheduled Sessions (IST): {timings}")
    print(f"🎯 Trades per Session: {s.get('trades_per_session')}")
    print(f"📊 Monitored Watchlist: {len(TARGET_ASSETS)} High-Payout OTC Pairs")
    print("=" * 70)


def main() -> None:
    # 1. Initialize Database & Settings
    initialize_db()
    print_banner()

    # 2. Initialize Telegram Bot
    bot = telebot.TeleBot(BOT_TOKEN)

    # 3. Start Live Market Feed Daemon
    print("[1/3] 🔄 Starting Real-Time Market Data Streamer...")
    start_market_feed()
    time.sleep(2)

    # 4. Start Session & Sticker Automation Scheduler
    print("[2/3] ⏰ Launching 24/7 Background Session Scheduler...")
    start_scheduler()
    time.sleep(1)

    # 5. Register Admin Panel Handlers
    print("[3/3] ⚙️ Initializing Interactive Telegram Admin Panel (/admin)...")
    register_admin_handlers(bot)

    print("\n✅ ALL MODULES LOADED & ACTIVE!")
    print("👉 Send /admin or /start to your bot in private chat to open the Dashboard.\n")

    # 6. Start Telegram Bot Listener (Infinity Polling with Auto-Reconnect)
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"⚠️ [Telegram Polling Glitch]: {e}. Reconnecting in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Bot shutdown gracefully by admin.")
        sys.exit(0)