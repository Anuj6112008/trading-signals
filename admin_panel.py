import telebot
from telebot import types
from typing import Dict, Any
from config import BOT_TOKEN, ADMIN_IDS
from database import get_all_settings, update_setting
from scheduler import run_session, is_session_active
import threading

# Admin state memory for multi-step inputs
_user_states: Dict[int, str] = {}


def is_admin(user_id: int) -> bool:
    """Checks if the user has admin privileges. If ADMIN_IDS is empty, allows all private chats."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def get_admin_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Generates the main interactive admin dashboard keyboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_channel = types.InlineKeyboardButton("📢 Set Target Channel", callback_data="set_channel")
    btn_sessions = types.InlineKeyboardButton("🔢 No. of Sessions", callback_data="set_sessions")
    btn_timings = types.InlineKeyboardButton("⏰ Session Timings", callback_data="set_timings")
    btn_trades = types.InlineKeyboardButton("🎯 Trades per Session", callback_data="set_trades")
    btn_link = types.InlineKeyboardButton("🔗 Broker Login Link", callback_data="set_link")
    btn_msg = types.InlineKeyboardButton("✍️ Closing Message", callback_data="set_msg")
    btn_start_now = types.InlineKeyboardButton("🚀 Start Session NOW (Test)", callback_data="start_now")
    btn_refresh = types.InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_panel")

    markup.add(btn_channel, btn_sessions)
    markup.add(btn_timings, btn_trades)
    markup.add(btn_link, btn_msg)
    markup.add(btn_start_now)
    markup.add(btn_refresh)
    return markup


def build_status_text() -> str:
    """Formats the current bot configuration settings for the dashboard."""
    s = get_all_settings()
    timings_str = ", ".join(s.get("session_timings", []))
    session_status = "🟢 ACTIVE (Running)" if is_session_active() else "⚪ IDLE (Waiting for Schedule)"

    return (
        "⚙️ **POCKET OPTION BOT — ADMIN DASHBOARD** ⚙️\n\n"
        f"📊 **Live Status:** {session_status}\n"
        f"📢 **Target Channel:** `{s.get('target_channel')}`\n"
        f"🔢 **Daily Sessions:** `{s.get('num_sessions')}`\n"
        f"⏰ **Session Timings (IST):** `{timings_str}`\n"
        f"🎯 **Trades per Session:** `{s.get('trades_per_session')}`\n"
        f"🔗 **Broker Link:** {s.get('login_link')}\n\n"
        f"✍️ **Closing Message:**\n_{s.get('closing_message')}_\n\n"
        "👇 *Select an option below to configure settings:*"
    )


def register_admin_handlers(bot: telebot.TeleBot) -> None:
    """Registers all command, callback query, and text handlers for the admin panel."""

    @bot.message_handler(commands=['admin', 'settings', 'panel', 'start'])
    def handle_admin_start(message: types.Message):
        if message.chat.type != "private":
            return
        if not is_admin(message.from_user.id):
            bot.reply_to(message, "⛔ Unauthorized access.")
            return

        bot.send_message(
            message.chat.id,
            build_status_text(),
            reply_markup=get_admin_menu_keyboard(),
            parse_mode="Markdown"
        )

    @bot.callback_query_handler(func=lambda call: True)
    def handle_callback(call: types.CallbackQuery):
        if not is_admin(call.from_user.id):
            bot.answer_callback_query(call.id, "Unauthorized.", show_alert=True)
            return

        data = call.data
        chat_id = call.message.chat.id

        if data == "refresh_panel":
            bot.edit_message_text(
                build_status_text(),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=get_admin_menu_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id, "Dashboard updated!")

        elif data == "set_channel":
            _user_states[chat_id] = "WAITING_CHANNEL"
            msg = (
                "📢 **Set Target Channel**\n\n"
                "• For **Public Channel:** Send username (e.g. `@WebDealx`)\n"
                "• For **Private Channel:** Send ID (e.g. `-1001234567890`)\n\n"
                "⚠️ *Make sure the bot is added as Admin in the channel.*"
            )
            bot.send_message(chat_id, msg, parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_sessions":
            _user_states[chat_id] = "WAITING_SESSIONS"
            bot.send_message(chat_id, "🔢 Enter the **Number of Daily Sessions** (e.g. `2` or `3`):", parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_timings":
            _user_states[chat_id] = "WAITING_TIMINGS"
            msg = (
                "⏰ **Set Session Timings (24-Hour IST Format)**\n\n"
                "Send comma-separated times:\n"
                "👉 Example: `14:00, 18:30, 21:00`"
            )
            bot.send_message(chat_id, msg, parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_trades":
            _user_states[chat_id] = "WAITING_TRADES"
            bot.send_message(chat_id, "🎯 Enter the **Number of Trades per Session** (e.g. `5`):", parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_link":
            _user_states[chat_id] = "WAITING_LINK"
            bot.send_message(chat_id, "🔗 Send the **Broker Registration / Login Link**:\n(Sent 10 mins before session)", parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_msg":
            _user_states[chat_id] = "WAITING_MSG"
            bot.send_message(chat_id, "✍️ Send the **Closing Review / Testimonial Message**:\n(Sent after session ends)", parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "start_now":
            if is_session_active():
                bot.answer_callback_query(call.id, "⚠️ A session is already active!", show_alert=True)
                return

            s = get_all_settings()
            ch = s.get("target_channel", "@webdealx")
            tr = int(s.get("trades_per_session", 5))

            bot.answer_callback_query(call.id, "🚀 Launching instant session...", show_alert=True)
            t = threading.Thread(target=run_session, args=(ch, tr), daemon=True)
            t.start()

            bot.send_message(chat_id, f"🚀 **Session launched instantly in `{ch}`!**", parse_mode="Markdown")

    @bot.message_handler(func=lambda msg: msg.chat.id in _user_states and msg.chat.type == "private")
    def handle_admin_inputs(message: types.Message):
        chat_id = message.chat.id
        state = _user_states.pop(chat_id, None)
        text = message.text.strip()

        if state == "WAITING_CHANNEL":
            update_setting("target_channel", text)
            bot.send_message(chat_id, f"✅ **Target Channel updated to:** `{text}`", parse_mode="Markdown")

        elif state == "WAITING_SESSIONS":
            try:
                count = int(text)
                update_setting("num_sessions", count)
                bot.send_message(chat_id, f"✅ **Daily Sessions set to:** `{count}`", parse_mode="Markdown")
            except ValueError:
                bot.send_message(chat_id, "❌ Invalid number. Please enter a valid integer.")

        elif state == "WAITING_TIMINGS":
            times = [t.strip() for t in text.split(",") if ":" in t]
            if times:
                update_setting("session_timings", times)
                update_setting("num_sessions", len(times))
                bot.send_message(chat_id, f"✅ **Session Timings updated to:** `{', '.join(times)}`", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, "❌ Invalid format. Example: `14:00, 19:00`")

        elif state == "WAITING_TRADES":
            try:
                trades = int(text)
                update_setting("trades_per_session", trades)
                bot.send_message(chat_id, f"✅ **Trades per session set to:** `{trades}`", parse_mode="Markdown")
            except ValueError:
                bot.send_message(chat_id, "❌ Invalid number. Please enter a valid integer.")

        elif state == "WAITING_LINK":
            update_setting("login_link", text)
            bot.send_message(chat_id, f"✅ **Broker Login Link updated!**", parse_mode="Markdown")

        elif state == "WAITING_MSG":
            update_setting("closing_message", text)
            bot.send_message(chat_id, f"✅ **Closing Message updated!**", parse_mode="Markdown")

        # Show updated dashboard
        bot.send_message(chat_id, build_status_text(), reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown")