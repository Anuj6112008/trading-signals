import time
import re
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
import telebot
from config import (
    BOT_TOKEN, 
    IST, 
    ALL_OTC_PAIRS,
    CUSTOM_EMOJI_IDS,
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


def parse_expiry_seconds(expiry_text: str) -> int:
    """
    Extracts the number of minutes from any expiry string (including Math Bold digits like 𝟏, 𝟓)
    and converts to seconds.
    """
    normalized = ""
    for ch in str(expiry_text):
        if '0' <= ch <= '9':
            normalized += ch
        elif '\U0001D7CE' <= ch <= '\U0001D7D7':  # Mathematical Bold 𝟎-𝟗
            normalized += str(ord(ch) - 0x1D7CE)

    match = re.search(r'\d+', normalized)
    if match:
        mins = int(match.group())
        return max(1, mins) * 60
    return 60  # Default to 1 minute (60s)


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


def e(key: str, fallback: str) -> str:
    """Returns custom emoji HTML tag if configured, else returns standard Unicode fallback."""
    emoji_id = CUSTOM_EMOJI_IDS.get(key, "").strip()
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'
    return fallback


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


def _broadcast_text(text: str, parse_mode: Optional[str] = "HTML") -> None:
    """Broadcasts a formatted message to all configured target channels."""
    channels = get_channels()
    for ch in channels:
        try:
            bot.send_message(ch, text, parse_mode=parse_mode)
        except Exception:
            try:
                bot.send_message(ch, text)
            except Exception as e:
                print(f"❌ Error sending message to {ch}: {e}")


def _execute_single_trade(trade_number: int, total_trades: int) -> None:
    """
    Executes a single trade sequence:
    1. At :30s: Sends Pre-Alert (Message 1).
    2. At :55s: Sends Direction Alert (Message 2).
    3. Trade opens at :00s.
    """
    # -------------------------------------------------------------
    # 1. ALIGN TO :30s MARK & SEND MESSAGE 1 (PRE-ALERT AT :30s)
    # -------------------------------------------------------------
    while get_now_ist().second != 30:
        time.sleep(0.5)

    opportunity = find_next_trading_opportunity()
    if not opportunity:
        pair_meta = ALL_OTC_PAIRS[0]
        direction, lead, price = "CALL", "Market Flow", 1.08250
    else:
        pair_meta, direction, lead, price = opportunity

    now = get_now_ist()
    sent_time = now.strftime("%H:%M:30")
    bold_pair = to_bold_font(pair_meta['display'])

    expiry_txt = get_setting("expiry_text", "𝟏 𝙈𝙞𝙣𝙪𝙩𝙚𝙨")
    invest_txt = get_setting("investment_text", "𝟓%")

    # MESSAGE 1: PRE-ALERT (Sent at :30s - No Entry Time line)
    pre_alert_text = (
        f"{e('hourglass', '⏳')} <b>GET READY -UPCOMING SIGNAL</b> {e('hourglass', '⏳')}\n\n"
        f"{e('diamond', '🔹')} Pair: <b>{bold_pair}</b>\n"
        f"{e('stopwatch', '⏱️')} Expiry: <b>{expiry_txt}</b>\n"
        f"{e('money', '🤑')} Investment : <b>{invest_txt}</b>\n\n"
        f"{e('warning', '⚠️')} <b><i>𝘽𝙚 𝙧𝙚𝙖𝙙𝙮 𝙬𝙞𝙩𝙝 𝙩𝙝𝙚  𝙥𝙖𝙞𝙧 &\n\n"
        f" 𝙨𝙚𝙩 𝙞𝙣𝙫𝙚𝙨𝙩𝙢𝙚𝙣𝙩! 𝘿𝙞𝙧𝙚𝙘𝙩𝙞𝙤𝙣 𝙘𝙤𝙢𝙞𝙣𝙜…..</i></b>"
    )
    _broadcast_text(pre_alert_text, parse_mode="HTML")
    print(f"📢 [TRADE #{trade_number} PRE-ALERT SENT AT :30s] {sent_time} -> {pair_meta['display']}")

    # -------------------------------------------------------------
    # 2. WAIT 25 SECONDS (Reaches :55s - EXACT 5 SECONDS BEFORE ENTRY)
    # -------------------------------------------------------------
    time.sleep(25)

    # -------------------------------------------------------------
    # 3. SEND MESSAGE 2 (DIRECTION ALERT AT :55s)
    # -------------------------------------------------------------
    dir_sent_time = get_now_ist().strftime("%H:%M:55")

    if direction == "CALL":
        dir_badge = f"{e('green_circle', '🟢')} <b><i>𝘽𝙐𝙔 (𝘾𝘼𝙇𝙇)</i></b>"
    else:
        dir_badge = f"{e('red_circle', '🔴')} <b><i>𝙎𝙀𝙇𝙇 (𝙋𝙐𝙏)</i></b>"

    entry_text = (
        f"{e('zap', '⚡')}<b>SIGNAL CONFIRMED -TAKE ENTRY</b>{e('zap', '⚡')}\n\n"
        f"{e('diamond', '🔹')} Pair: <b>{pair_meta['display']}</b>\n\n"
        f"{e('target', '🎯')} Direction: {dir_badge}\n\n"
        f"{e('stopwatch', '⏱️')} Expiry: <b>{expiry_txt}</b>\n\n"
        f"{e('pointer', '👉')} <b>ALWAYS ENTER IN FRESH CANDLE</b>"
    )
    _broadcast_text(entry_text, parse_mode="HTML")
    print(f"🚀 [TRADE #{trade_number} DIRECTION SENT AT :55s] {dir_sent_time} -> {pair_meta['display']} | {direction}")


def run_session(total_trades: int) -> None:
    """Orchestrates an active trading session from start to finish."""
    global _is_session_running
    _is_session_running = True

    channels = get_channels()
    print(f"\n🚀 [SESSION STARTED] Active Channels: {', '.join(channels)} | Total Trades: {total_trades}")

    # 1. Send Session Started Sticker (WebDealx/411)
    _broadcast_sticker(MSG_ID_START_STICKER)
    time.sleep(5)

    # 2. Execute trades sequentially with Dynamic (Expiry + 30s + 60s) intervals
    for trade_idx in range(1, total_trades + 1):
        if _stop_event.is_set():
            break

        # Execute Trade (Pre-Alert at :30s -> Direction at :55s)
        _execute_single_trade(trade_idx, total_trades)

        # Dynamic Post-Trade Gap if there is a next trade
        if trade_idx < total_trades:
            expiry_str = get_setting("expiry_text", "𝟏 𝙈𝙞𝙣𝙪𝙩𝙚𝙨")
            expiry_secs = parse_expiry_seconds(expiry_str)

            print(f"\n⏳ [TRADE #{trade_idx} RUNNING] Waiting for Expiry ({expiry_secs}s)...")
            time.sleep(expiry_secs)  # 1. Wait for trade expiry to complete

            print(f"⏳ [POST-EXPIRY WAIT] Waiting 30s before sending 'NEXT ONE' Sticker...")
            time.sleep(30)          # 2. Wait 30s

            print(f"🖼️ [{get_now_ist().strftime('%I:%M:%S %p IST')}] Sending 'NEXT ONE' Sticker for Trade #{trade_idx + 1}...")
            _broadcast_sticker(MSG_ID_NEXT_TRADE_STICKER)  # 3. Send Next One Sticker

            print(f"⏳ [POST-STICKER WAIT] Waiting 60s before Trade #{trade_idx + 1}...")
            time.sleep(60)          # 4. Wait 60s -> Next trade loop aligns to :30s pre-alert

    # -------------------------------------------------------------
    # 3. SESSION END: Wait Expiry + 2-MIN GAPS SEQUENTIAL
    # -------------------------------------------------------------
    expiry_str = get_setting("expiry_text", "𝟏 𝙈𝙞𝙣𝙪𝙩𝙚𝙨")
    last_expiry_secs = parse_expiry_seconds(expiry_str)
    print(f"\n🏁 [LAST TRADE RUNNING] Waiting {last_expiry_secs}s (Expiry) + 120s before Message 1...")
    time.sleep(last_expiry_secs + 120)

    msg_1 = get_setting("closing_msg_1", "Session completed!")
    msg_2 = get_setting("closing_msg_2", "Thnx for attending the session\nKindly send your reviews/ testimonials on @traderskull")
    msg_3 = get_setting("closing_msg_3", "See you in next session!")

    # Message 1
    _broadcast_text(msg_1, parse_mode="HTML")
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ✍️ Closing Message 1 sent. Waiting 2 mins...")
    time.sleep(120)

    # Message 2
    _broadcast_text(msg_2, parse_mode="HTML")
    print(f"[{get_now_ist().strftime('%I:%M:%S %p IST')}] ✍️ Closing Message 2 sent. Waiting 2 mins...")
    time.sleep(120)

    # Message 3
    _broadcast_text(msg_3, parse_mode="HTML")
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
                            f"🔔 <b>SESSION STARTING IN 10 MINUTES!</b> 🔔\n\n"
                            f"Make sure you are logged in and your account is ready.\n\n"
                            f"🔗 <b>Broker Login / Registration Link:</b>\n👉 {login_link}"
                        )
                        _broadcast_text(link_text, parse_mode="HTML")
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
