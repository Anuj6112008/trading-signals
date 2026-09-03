import time
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import telebot
from config import BOT_TOKEN, IST, TARGET_ASSETS
from database import get_setting, get_channels
from strategy import find_next_trading_opportunity

bot = telebot.TeleBot(BOT_TOKEN)

# Scheduler State
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_is_session_running: bool = False

# Sticker Channel & IDs
STICKER_SOURCE_CHANNEL = "@WebDealx"
MSG_ID_5MIN_STICKER = 410
MSG_ID_START_STICKER = 411
MSG_ID_END_STICKER = 414
MSG_ID_NEXT_TRADE_STICKER = 416


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
    """Converts regular text to Mathematical Bold Unicode font."""
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


def _delete_message_across_channels(msg_ids: Dict[str, int]) -> None:
    """Deletes sent messages/stickers across channels."""
    for ch, m_id in msg_ids.items():
        try:
            bot.delete_message(chat_id=ch, message_id=m_id)
        except Exception:
            pass


def _execute_single_trade(trade_number: int, total_trades: int) -> None:
    """
    Executes a single trade cycle:
    1. Sends 'NEXT ONE' Sticker 30 seconds before trade (WITHOUT DELETING).
    2. Sends T-15 Pre-Alert at :45s.
    3. Waits exact 15 seconds.
    4. Sends Confirmed Direction Alert at :00s.
    """
    # -------------------------------------------------------------
    # 1. SEND 'NEXT ONE' STICKER EXACT 30 SECONDS BEFORE PRE-ALERT
    # -------------------------------------------------------------
    while get_now_ist().second != 15:
        time.sleep(0.5)

    print(f"\n[{get_now_ist().strftime('%I:%M:%S %p IST')}] 🖼️ Sending 'NEXT ONE' Sticker 30s before trade #{trade_number} (No Deletion)...")
    _broadcast_sticker(MSG_ID_NEXT_TRADE_STICKER)

    # Wait 30 seconds to reach :45s mark
    while get_now_ist().second != 45:
        time.sleep(0.5)

    # -------------------------------------------------------------
    # 2. FIND BEST PAIR & DISPATCH MESSAGE 1 (PRE-ALERT AT :45s)
    # -------------------------------------------------------------
    opportunity = find_next_trading_opportunity()
    if not opportunity:
        pair_meta = TARGET_ASSETS[0]
        direction, lead, price = "CALL", "Market Momentum", 1.08250
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
    print(f"📢 [MESSAGE 1 PRE-ALERT] {sent_time} -> {pair_meta['display']} | Target: {entry_target_time}")

    # -------------------------------------------------------------
    # 3. WAIT EXACT 15 SECONDS (Reaches :00s Candle Open)
    # -------------------------------------------------------------
    time.sleep(15)

    # -------------------------------------------------------------
    # 4. DISPATCH MESSAGE 2 (CONFIRMED DIRECTION AT :00s)
    # -------------------------------------------------------------
    entry_now_time = get_now_ist().strftime("%H:%M:00")

    if direction == "CALL":
        dir_badge = "🟢 𝘽𝙐𝙔 (𝘾𝘼𝙇𝙇)"
    else:
        dir_badge = "🔴 𝙎𝙀𝙇𝙇 (𝙋𝙐𝙏)"

    entry_text = (
        "⚡SIGNAL CONFIRMED -TAKE ENTRY⚡\n\n"
        f"🔹 Pair: {pair_meta['display']}\n\n"
        f"🎯 Direction: {dir_badge}\n\n"
        f"⏰ Exact Entry Time: {entry_now_time}\n"
        "⏱️ Expiry: 1 Minute\n\n"
        "👉 ALWAYS ENTER IN FRESH CANDLE"
    )

    _broadcast_text(entry_text)
    print(f"🚀 [MESSAGE 2 DIRECTION] {entry_now_time} -> {pair_meta['display']} | {direction}")


def run_session(total_trades: int) -> None:
    """Orchestrates an active trading session from start to finish."""
    global _is_session_running
    _is_session_running = True

    channels = get_channels()
    print(f"\n🚀 [SESSION STARTED] Active Channels: {', '.join(channels)} | Total Trades: {total_trades}")

    # 1. Send Session Started Sticker (WebDealx/411)
    _broadcast_sticker(MSG_ID_START_STICKER)
    time.sleep(5)

    # 2. Execute trades sequentially with 3-minute intervals
    for trade_idx in range(1, total_trades + 1):
        if _stop_event.is_set():
            break
        
        _execute_single_trade(trade_idx, total_trades)

        # Wait 3 minutes before next trade
        if trade_idx < total_trades:
            print(f"⏳ Waiting 3 minutes before Trade #{trade_idx + 1}...")
            time.sleep(110)

    # 3. Session End: Send Closing Sticker (WebDealx/414)
    print(f"\n🏁 [SESSION ENDED] Sending closing sticker ({MSG_ID_END_STICKER}) and review message...")
    _broadcast_sticker(MSG_ID_END_STICKER)
    time.sleep(3)

    # 4. Post Closing Message
    closing_msg = get_setting("closing_message", "Thnx for attending the session\nKindly send your reviews/ testimonials on @traderskull")
    _broadcast_text(closing_msg)

    _is_session_running = False


def _scheduler_worker() -> None:
    """Main automated schedule monitor checking 10m, 5m, and session start events."""
    last_10m_sent_events = set()
    last_5m_sticker_ids: Dict[str, int] = {}
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
                # EVENT 2: T-5 MINUTES BEFORE (Send 410 Sticker)
                # -------------------------------------------------------------
                if 240 <= diff_seconds <= 330:
                    if event_key_5m not in last_5m_sent_events:
                        channels = get_channels()
                        last_5m_sticker_ids.clear()
                        for ch in channels:
                            try:
                                sent = bot.copy_message(chat_id=ch, from_chat_id=STICKER_SOURCE_CHANNEL, message_id=MSG_ID_5MIN_STICKER)
                                last_5m_sticker_ids[ch] = sent.message_id
                            except Exception:
                                pass
                        last_5m_sent_events.add(event_key_5m)
                        print(f"[{now.strftime('%I:%M:%S %p IST')}] ⏳ Posted 5-Min Sticker ({MSG_ID_5MIN_STICKER}) for {s_time} session.")

                # -------------------------------------------------------------
                # EVENT 3: SESSION START (Delete 410 Sticker & Start Session)
                # -------------------------------------------------------------
                if -20 <= diff_seconds <= 20:
                    if event_key_start not in last_started_sessions:
                        last_started_sessions.add(event_key_start)

                        # Delete 5m sticker across channels
                        if last_5m_sticker_ids:
                            _delete_message_across_channels(last_5m_sticker_ids)
                            last_5m_sticker_ids.clear()

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
