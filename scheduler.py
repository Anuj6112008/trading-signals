import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import telebot
from config import BOT_TOKEN, IST, TARGET_ASSETS
from database import get_setting
from strategy import find_next_trading_opportunity

bot = telebot.TeleBot(BOT_TOKEN)

# Scheduler State
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_is_session_running: bool = False

# Sticker Message IDs tracking for deletion
STICKER_SOURCE_CHANNEL = "@WebDealx"
MSG_ID_5MIN_STICKER = 410
MSG_ID_START_STICKER = 411
MSG_ID_END_STICKER = 414
MSG_ID_WAIT_STICKER = 416


def get_now_ist() -> datetime:
    """Returns current Indian Standard Time."""
    return datetime.now(IST)


def _send_media_from_channel(target_channel: str, message_id: int) -> Optional[int]:
    """Copies the exact sticker from WebDealx channel into the target channel."""
    try:
        sent = bot.copy_message(chat_id=target_channel, from_chat_id=STICKER_SOURCE_CHANNEL, message_id=message_id)
        return sent.message_id
    except Exception:
        # Fallback to forward if copy is restricted
        try:
            sent = bot.forward_message(chat_id=target_channel, from_chat_id=STICKER_SOURCE_CHANNEL, message_id=message_id)
            return sent.message_id
        except Exception as e:
            print(f"❌ Error sending sticker {message_id}: {e}")
            return None


def _delete_message(target_channel: str, message_id: Optional[int]) -> None:
    """Safely deletes a message or sticker from the target channel."""
    if message_id is None:
        return
    try:
        bot.delete_message(chat_id=target_channel, message_id=message_id)
    except Exception:
        pass


def _execute_single_trade(target_channel: str, trade_number: int, total_trades: int) -> None:
    """
    Executes the 2-Step Trade sequence:
    1. Sends waiting sticker (WebDealx/416), waits 3 mins, then deletes it.
    2. Sends T-15 Pre-Alert at :45s.
    3. Sends T-5 Direction Alert at :55s.
    """
    # -----------------------------------------------------------------
    # 1. SEND WAITING STICKER & 3-MINUTE GAP
    # -----------------------------------------------------------------
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ⏳ Sending Waiting Sticker ({MSG_ID_WAIT_STICKER}) for Trade #{trade_number}...")
    wait_sticker_id = _send_media_from_channel(target_channel, MSG_ID_WAIT_STICKER)

    # 3-Minute Cooldown before scanning
    time.sleep(170)  # Wait ~2m 50s

    # Align to the next :45 second mark
    while get_now_ist().second != 45:
        time.sleep(0.5)

    # Delete waiting sticker before sending trade
    _delete_message(target_channel, wait_sticker_id)

    # -----------------------------------------------------------------
    # 2. FIND CANDIDATE & DISPATCH T-15 PRE-ALERT (:45s)
    # -----------------------------------------------------------------
    opportunity = find_next_trading_opportunity()
    if not opportunity:
        # Fallback to first available asset
        pair_meta = TARGET_ASSETS[0]
        direction, lead, price = "CALL", "Market Flow", 1.08250
    else:
        pair_meta, direction, lead, price = opportunity

    now = get_now_ist()
    sent_time = now.strftime("%H:%M:45")
    entry_target_time = (now + timedelta(seconds=15)).strftime("%H:%M:00")
    display = pair_meta['display']
    payout = pair_meta['payout']

    pre_alert_text = (
        f"⏳ **GET READY — UPCOMING SIGNAL** ⏳\n\n"
        f"🔹 **Pair:** {display}\n"
        f"🔹 **Payout:** {payout}%\n"
        f"⏱️ **Expiry:** 1 Minute (M1)\n"
        f"⏰ **Entry Target:** `{entry_target_time} IST` (In 15s)\n\n"
        f"⚠️ *Open broker, select pair & set investment! Direction coming in 10s...*"
    )
    try:
        bot.send_message(target_channel, pre_alert_text, parse_mode="Markdown")
        print(f"\n📢 [TRADE #{trade_number} PRE-ALERT] {sent_time} -> {display} | Target: {entry_target_time}")
    except Exception as e:
        print(f"❌ Telegram Error (Pre-alert): {e}")

    # -----------------------------------------------------------------
    # 3. WAIT 10 SECONDS (Reaches :55s - 5-SECOND ADVANCE DIRECTION)
    # -----------------------------------------------------------------
    time.sleep(10)

    dir_sent_time = get_now_ist().strftime("%H:%M:55")
    if direction == "CALL":
        dir_badge = "🟢 **BUY (CALL)** 🟢"
        action_note = "Press **GREEN (UP)** at :00s!"
    else:
        dir_badge = "🔴 **SELL (PUT)** 🔴"
        action_note = "Press **RED (DOWN)** at :00s!"

    entry_text = (
        f"⚡ **SIGNAL CONFIRMED — TAKE ENTRY** ⚡\n\n"
        f"🔹 **Pair:** {display}\n"
        f"🎯 **Direction:** {dir_badge}\n"
        f"⏰ **Exact Entry Time:** `{entry_target_time} IST` (In 5s)\n"
        f"⏱️ **Expiry:** 1 Minute (Fixed)\n"
        f"🔹 **Trade Count:** #{trade_number}/{total_trades}\n\n"
        f"👉 *{action_note}*"
    )

    try:
        bot.send_message(target_channel, entry_text, parse_mode="Markdown")
        print(f"🚀 [TRADE #{trade_number} DIRECTION] {dir_sent_time} -> {display} | {direction}")
    except Exception as e:
        print(f"❌ Telegram Error (Direction): {e}")


def run_session(target_channel: str, total_trades: int) -> None:
    """Orchestrates an active trading session from start to finish."""
    global _is_session_running
    _is_session_running = True

    print(f"\n🚀 [SESSION STARTED] Target Channel: {target_channel} | Total Trades: {total_trades}")

    # 1. Send Session Started Sticker (WebDealx/411)
    _send_media_from_channel(target_channel, MSG_ID_START_STICKER)
    time.sleep(5)

    # 2. Execute target trades sequentially with 3-minute gaps
    for trade_idx in range(1, total_trades + 1):
        if _stop_event.is_set():
            break
        _execute_single_trade(target_channel, trade_idx, total_trades)

    # 3. Session End: Send Sticker (WebDealx/414)
    print(f"\n🏁 [SESSION ENDED] Sending closing sticker ({MSG_ID_END_STICKER}) and review message...")
    _send_media_from_channel(target_channel, MSG_ID_END_STICKER)
    time.sleep(3)

    # 4. Post Closing Message
    closing_msg = get_setting("closing_message")
    try:
        bot.send_message(target_channel, closing_msg, parse_mode="Markdown")
    except Exception as e:
        print(f"❌ Error sending closing message: {e}")

    _is_session_running = False


def _scheduler_worker() -> None:
    """Main automated schedule monitor checking 10m, 5m, and session start events."""
    last_10m_sent_date_time = ""
    last_5m_sticker_info = {"date_time": "", "msg_id": None}

    print("⏰ [SCHEDULER RUNNING] Monitoring configured session timings 24/7...")

    while not _stop_event.is_set():
        if not get_setting("is_bot_active", True) or _is_session_running:
            time.sleep(5)
            continue

        now = get_now_ist()
        current_time_str = now.strftime("%H:%M")
        current_date_str = now.strftime("%Y-%m-%d")

        target_channel = get_setting("target_channel", "@webdealx")
        session_timings = get_setting("session_timings", ["14:00", "19:00"])
        trades_per_session = int(get_setting("trades_per_session", 5))
        login_link = get_setting("login_link")

        for s_time in session_timings:
            try:
                s_hour, s_minute = map(int, s_time.split(":"))
                session_dt = now.replace(hour=s_hour, minute=s_minute, second=0, microsecond=0)
                diff_seconds = (session_dt - now).total_seconds()

                # -------------------------------------------------------------
                # EVENT 1: T-10 MINUTES BEFORE (Post Login Link)
                # -------------------------------------------------------------
                if 570 <= diff_seconds <= 630:  # ~10 minutes window
                    event_key = f"{current_date_str}_{s_time}_10m"
                    if last_10m_sent_date_time != event_key:
                        link_text = (
                            f"🔔 **SESSION STARTING IN 10 MINUTES!** 🔔\n\n"
                            f"Make sure you are logged in and your account is ready.\n\n"
                            f"🔗 **Broker Login / Registration Link:**\n👉 {login_link}"
                        )
                        try:
                            bot.send_message(target_channel, link_text, parse_mode="Markdown")
                            last_10m_sent_date_time = event_key
                            print(f"[{now.strftime('%I:%M:%S %p IST')}] 🔗 Posted 10-Min Login Link for {s_time} session.")
                        except Exception as e:
                            print(f"❌ Error sending 10m login link: {e}")

                # -------------------------------------------------------------
                # EVENT 2: T-5 MINUTES BEFORE (Send 410 Sticker)
                # -------------------------------------------------------------
                if 270 <= diff_seconds <= 330:  # ~5 minutes window
                    event_key = f"{current_date_str}_{s_time}_5m"
                    if last_5m_sticker_info["date_time"] != event_key:
                        stk_id = _send_media_from_channel(target_channel, MSG_ID_5MIN_STICKER)
                        last_5m_sticker_info = {"date_time": event_key, "msg_id": stk_id}
                        print(f"[{now.strftime('%I:%M:%S %p IST')}] ⏳ Posted 5-Min Sticker ({MSG_ID_5MIN_STICKER}) for {s_time} session.")

                # -------------------------------------------------------------
                # EVENT 3: SESSION START (Delete 410 Sticker & Start Session)
                # -------------------------------------------------------------
                if -15 <= diff_seconds <= 30 and current_time_str == s_time:
                    # Delete 5m sticker if sent
                    if last_5m_sticker_info.get("msg_id"):
                        _delete_message(target_channel, last_5m_sticker_info["msg_id"])
                        last_5m_sticker_info = {"date_time": "", "msg_id": None}

                    # Launch Session in dedicated thread
                    t = threading.Thread(
                        target=run_session,
                        args=(target_channel, trades_per_session),
                        daemon=True,
                        name=f"SessionThread_{s_time}"
                    )
                    t.start()
                    break

            except Exception as e:
                print(f"❌ Scheduler check error for {s_time}: {e}")

        time.sleep(5)


def start_scheduler() -> None:
    """Launches the background scheduler thread."""
    global _scheduler_thread
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_worker, daemon=True, name="SchedulerWorker")
    _scheduler_thread.start()


def is_session_active() -> bool:
    """Returns True if a live session is currently running."""
    return _is_session_running