import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import telebot
from config import (
    BOT_TOKEN, 
    IST, 
    ALL_OTC_PAIRS,
    STICKER_SOURCE_CHANNEL,
    MSG_ID_5MIN_STICKER,
    MSG_ID_START_STICKER,
    MSG_ID_END_STICKER,
    MSG_ID_NEXT_TRADE_STICKER
)
from database import get_setting, get_channels
from strategy import find_next_trading_opportunity

bot = telebot.TeleBot(BOT_TOKEN)

# Scheduler State
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_is_session_running: bool = False


def get_now_ist() -> datetime:
    """Returns current Indian Standard Time."""
    return datetime.now(IST)


def normalize_time_str(time_str: str) -> str:
    """Ensures time is always formatted with leading zeros (e.g. '1:48' -> '01:48')."""
    try:
        parts = time_str.strip().split(":")
        h = int(parts[0])
        m = int(parts[1])
        return f"{h:02d}:{m:02d}"
    except Exception:
        return time_str.strip()


def to_bold_font(text: str) -> str:
    """Converts regular text to Mathematical Bold Unicode font (e.g. USD/JPY -> 𝐔𝐒𝐃/𝐉𝐏𝐘)."""
    result = []
    for char in text:
        if 'A' <= char <= 'Z':
            result.append(chr(ord(char) - ord('A') + 0x1D400))
        elif 'a' <= char <= 'z':
            result.append(chr(ord(char) - ord('a') + 0x1D41A))
        elif '0' <= char <= '9':
            result.append(chr(ord(char) - ord('0') + 0x1D7CE))
        else:
            result.append(char)
    return "".join(result)


def _broadcast_sticker(message_id: int) -> None:
    """Broadcasts a sticker to all configured target channels."""
    channels = get_channels()
    for ch in channels:
        try:
            bot.copy_message(chat_id=ch, from_chat_id=STICKER_SOURCE_CHANNEL, message_id=message_id)
        except Exception:
            try:
                bot.forward_message(chat_id=ch, from_chat_id=STICKER_SOURCE_CHANNEL, message_id=message_id)
            except Exception as e:
                print(f"❌ Error sending sticker {message_id} to {ch}: {e}")


def _broadcast_text(text: str) -> None:
    """Broadcasts a text message to all configured target channels."""
    channels = get_channels()
    for ch in channels:
        try:
            bot.send_message(ch, text)
        except Exception as e:
            print(f"❌ Error sending message to {ch}: {e}")


def _execute_single_trade(trade_number: int, total_trades: int) -> None:
    """
    Executes a single trade cycle:
    1. Trade #2+: Sends 'NEXT ONE' sticker 30 seconds before pre-alert (at :15s mark, no deletion).
    2. At :45s (T-15): Sends Pre-Alert.
    3. At :55s (T-5 - EXACT 5 SECONDS BEFORE ENTRY): Sends Confirmed Direction (BUY/SELL).
    4. Exact Entry Time is :00s.
    """
    # Send 'NEXT ONE' sticker starting from Trade #2 onwards
    if trade_number > 1:
        while get_now_ist().second != 15:
            time.sleep(0.5)

        print(f"\n[{get_now_ist().strftime('%I:%M:%S %p IST')}] 🖼️ Sending 'NEXT ONE' Sticker before Trade #{trade_number}...")
        _broadcast_sticker(MSG_ID_NEXT_TRADE_STICKER)

    # -------------------------------------------------------------
    # 1. ALIGN TO :45s MARK & SEND MESSAGE 1 (PRE-ALERT AT :45s)
    # -------------------------------------------------------------
    while get_now_ist().second != 45:
        time.sleep(0.5)

    opportunity = find_next_trading_opportunity()
    if not opportunity:
        pair_meta = ALL_OTC_PAIRS[0]
        direction, lead, price = "CALL", "Market Flow", 1.08250
    else:
        pair_meta, direction, lead, price = opportunity

    now = get_now_ist()
    sent_time = now.strftime("%H:%M:45")
    entry_target_time = (now + timedelta(seconds=15)).strftime("%H:%M:00")
    bold_pair = to_bold_font(pair_meta['display'])

    pre_alert_text = (
        "⏳ GET READY -UPCOMING SIGNAL ⏳\n\n"
        f"🔹 Pair: {bold_pair}\n"
        "⏱️ Expiry: 1 𝙈𝙞𝙣𝙪𝙩𝙚\n"
        "🤑 Investment : 𝟐%\n"
        f"⏰ Entry Target: {entry_target_time} IST (In 15s)\n\n"
        "⚠️ 𝘽𝙚 𝙧𝙚𝙖𝙙𝙮 𝙬𝙞𝙩𝙝 𝙩𝙝𝙚  𝙥𝙖𝙞𝙧 & 𝙨𝙚𝙩 𝙞𝙣𝙫𝙚𝙨𝙩𝙢𝙚𝙣𝙩! 𝘿𝙞𝙧𝙚𝙘𝙩𝙞𝙤𝙣 𝙘𝙤𝙢𝙞𝙣𝙜….."
    )
    _broadcast_text(pre_alert_text)
    print(f"📢 [TRADE #{trade_number} PRE-ALERT] {sent_time} -> {pair_meta['display']} | Entry Target: {entry_target_time}")

    # -------------------------------------------------------------
    # 2. WAIT 10 SECONDS (Reaches :55s - EXACT 5 SECONDS BEFORE ENTRY)
    # -------------------------------------------------------------
    time.sleep(10)

    # -------------------------------------------------------------
    # 3. SEND MESSAGE 2 (DIRECTION ALERT AT :55s)
    # -------------------------------------------------------------
    dir_sent_time = get_now_ist().strftime("%H:%M:55")

    if direction == "CALL":
        dir_badge = "🟢 𝘽𝙐𝙔 (𝘾𝘼𝙇𝙇)"
    else:
        dir_badge = "🔴 𝙎𝙀𝙇𝙇 (𝙋𝙐𝙏)"

    entry_text = (
        "⚡SIGNAL CONFIRMED -TAKE ENTRY⚡\n\n"
        f"🔹 Pair: {pair_meta['display']}\n\n"
        f"🎯 Direction: {dir_badge}\n\n"
        f"⏰ Exact Entry Time: {entry_target_time}\n"
        "⏱️ Expiry: 1 Minute\n\n"
        "👉 ALWAYS ENTER IN FRESH CANDLE"
    )
    _broadcast_text(entry_text)
    print(f"🚀 [TRADE #{trade_number} DIRECTION SENT (5s ADVANCE)] {dir_sent_time} -> {pair_meta['display']} | {direction} (Target: {entry_target_time})")


def run_session(total_trades: int) -> None:
    """Orchestrates an active trading session from start to finish."""
    global _is_session_running
    _is_session_running = True

    channels = get_channels()
    print(f"\n🚀 [SESSION STARTED] Active Channels: {', '.join(channels)} | Total Trades: {total_trades}")

    # 1. Send Session Started Sticker (WebDealx/411)
    _broadcast_sticker(MSG_ID_START_STICKER)
    time.sleep(5)

    # 2. Execute trades with 3-minute intervals
    for trade_idx in range(1, total_trades + 1):
        if _stop_event.is_set():
            break
        
        _execute_single_trade(trade_idx, total_trades)

        if trade_idx < total_trades:
            print(f"⏳ Waiting 3 minutes before Trade #{trade_idx + 1}...")
            time.sleep(110)

    # 3. Session End: 3 Sequential Closing Messages (2-min gap) + Delayed 414 Sticker
    print("\n🏁 [TRADES FINISHED] Starting Closing Messages Sequence (2-Min Gaps)...")
    
    msg_1 = get_setting("closing_msg_1", "Session completed!")
    msg_2 = get_setting("closing_msg_2", "Thnx for attending the session\nKindly send your reviews/ testimonials on @traderskull")
    msg_3 = get_setting("closing_msg_3", "See you in next session!")

    # Message 1
    _broadcast_text(msg_1)
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ✍️ Closing Message 1 sent. Waiting 2 mins...")
    time.sleep(120)

    # Message 2
    _broadcast_text(msg_2)
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ✍️ Closing Message 2 sent. Waiting 2 mins...")
    time.sleep(120)

    # Message 3
    _broadcast_text(msg_3)
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ✍️ Closing Message 3 sent. Waiting 2 mins...")
    time.sleep(120)

    # Session End Sticker (414) sent 2 mins after Message 3
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] 🏁 Sending Final End Sticker ({MSG_ID_END_STICKER})...")
    _broadcast_sticker(MSG_ID_END_STICKER)

    _is_session_running = False


def _scheduler_worker() -> None:
    """Main automated schedule monitor checking 10m, 5m, and session start events."""
    last_10m_sent_events = set()
    last_5m_sent_events = set()
    last_started_sessions = set()

    print("⏰ [SCHEDULER RUNNING] Monitoring configured session timings 24/7...")

    while not _stop_event.is_set():
        if not get_setting("is_bot_active", True) or _is_session_running:
            time.sleep(3)
            continue

        now = get_now_ist()
        current_date_str = now.strftime("%Y-%m-%d")

        raw_timings = get_setting("session_timings", ["14:00", "19:00"])
        trades_per_session = int(get_setting("trades_per_session", 5))
        login_link = get_setting("login_link")

        for raw_time in raw_timings:
            try:
                s_time = normalize_time_str(raw_time)
                s_hour, s_minute = map(int, s_time.split(":"))
                session_dt = now.replace(hour=s_hour, minute=s_minute, second=0, microsecond=0)
                diff_seconds = (session_dt - now).total_seconds()

                event_key_10m = f"{current_date_str}_{s_time}_10m"
                event_key_5m = f"{current_date_str}_{s_time}_5m"
                event_key_start = f"{current_date_str}_{s_time}_start"

                # -------------------------------------------------------------
                # EVENT 1: T-10 MINUTES BEFORE (Post Login Link)
                # -------------------------------------------------------------
                if 540 <= diff_seconds <= 630:
                    if event_key_10m not in last_10m_sent_events:
                        link_text = (
                            f"🔔 **SESSION STARTING IN 10 MINUTES!** 🔔\n\n"
                            f"Make sure you are logged in and your account is ready.\n\n"
                            f"🔗 **Broker Login / Registration Link:**\n👉 {login_link}"
                        )
                        _broadcast_text(link_text)
                        last_10m_sent_events.add(event_key_10m)
                        print(f"[{now.strftime('%I:%M:%S %p IST')}] 🔗 Posted 10-Min Login Link for {s_time} session.")

                # -------------------------------------------------------------
                # EVENT 2: T-5 MINUTES BEFORE (Send 410 Sticker - NO DELETION)
                # -------------------------------------------------------------
                if 240 <= diff_seconds <= 330:
                    if event_key_5m not in last_5m_sent_events:
                        _broadcast_sticker(MSG_ID_5MIN_STICKER)
                        last_5m_sent_events.add(event_key_5m)
                        print(f"[{now.strftime('%I:%M:%S %p IST')}] ⏳ Posted 5-Min Sticker ({MSG_ID_5MIN_STICKER}) for {s_time} session.")

                # -------------------------------------------------------------
                # EVENT 3: SESSION START
                # -------------------------------------------------------------
                if -20 <= diff_seconds <= 20:
                    if event_key_start not in last_started_sessions:
                        last_started_sessions.add(event_key_start)

                        # Launch Session in dedicated thread
                        t = threading.Thread(
                            target=run_session,
                            args=(trades_per_session,),
                            daemon=True,
                            name=f"SessionThread_{s_time}"
                        )
                        t.start()
                        break

            except Exception as e:
                print(f"❌ Scheduler check error for {raw_time}: {e}")

        time.sleep(2)


def start_scheduler() -> None:
    """Launches the background scheduler thread."""
    global _scheduler_thread
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_worker, daemon=True, name="SchedulerWorker")
    _scheduler_thread.start()


def is_session_active() -> bool:
    """Returns True if a live session is currently running."""
    return _is_session_running
