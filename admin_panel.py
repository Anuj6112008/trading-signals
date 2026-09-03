import telebot
from telebot import types
from typing import Dict, Any, List
from config import BOT_TOKEN, ADMIN_IDS
from database import get_all_settings, update_setting, get_channels, add_channel, remove_channel
from scheduler import run_session, is_session_active
import threading

# Admin state memory for multi-step text inputs
_user_states: Dict[int, str] = {}


def is_admin(user_id: int) -> bool:
    """Checks if the user has admin privileges. If ADMIN_IDS is empty, allows all private chats."""
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS


def get_cancel_keyboard() -> types.InlineKeyboardMarkup:
    """Generates a standalone Cancel inline button."""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_action"))
    return markup


def get_admin_menu_keyboard() -> types.InlineKeyboardMarkup:
    """Generates the main interactive admin dashboard keyboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn_channel_mgr = types.InlineKeyboardButton("📢 Channel Manager", callback_data="mgr_channels")
    btn_sessions = types.InlineKeyboardButton("🔢 No. of Sessions", callback_data="set_sessions")
    btn_timings = types.InlineKeyboardButton("⏰ Session Timings", callback_data="set_timings")
    btn_trades = types.InlineKeyboardButton("🎯 Trades per Session", callback_data="set_trades")
    btn_link = types.InlineKeyboardButton("🔗 Broker Login Link", callback_data="set_link")
    btn_msg = types.InlineKeyboardButton("✍️ Closing Message", callback_data="set_msg")
    btn_start_now = types.InlineKeyboardButton("🚀 Start Session NOW (Test)", callback_data="start_now")
    btn_refresh = types.InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_panel")

    markup.add(btn_channel_mgr)
    markup.add(btn_sessions, btn_timings)
    markup.add(btn_trades, btn_link)
    markup.add(btn_msg)
    markup.add(btn_start_now)
    markup.add(btn_refresh)
    return markup


def get_channel_manager_keyboard() -> types.InlineKeyboardMarkup:
    """Generates the channel management sub-menu keyboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_add = types.InlineKeyboardButton("➕ Add Channel", callback_data="ch_add")
    btn_del = types.InlineKeyboardButton("➖ Remove Channel", callback_data="ch_remove_menu")
    btn_back = types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_panel")
    markup.add(btn_add, btn_del)
    markup.add(btn_back)
    return markup


def get_remove_channels_keyboard() -> types.InlineKeyboardMarkup:
    """Generates dynamic buttons for each active channel to remove it with 1 tap."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    channels = get_channels()
    for ch in channels:
        markup.add(types.InlineKeyboardButton(f"🗑️ Remove {ch}", callback_data=f"delch_{ch}"))
    markup.add(types.InlineKeyboardButton("❌ Cancel / Back", callback_data="mgr_channels"))
    return markup


def build_status_text() -> str:
    """Formats the current bot configuration settings for the dashboard."""
    s = get_all_settings()
    channels = get_channels()
    channels_str = "\n".join([f"  • `{ch}`" for ch in channels]) if channels else "  • _None configured_"
    timings_str = ", ".join(s.get("session_timings", []))
    session_status = "🟢 ACTIVE (Running)" if is_session_active() else "⚪ IDLE (Waiting for Schedule)"

    return (
        "⚙️ **POCKET OPTION VIP BOT — ADMIN DASHBOARD** ⚙️\n\n"
        f"📊 **Live Status:** {session_status}\n\n"
        f"📢 **Target Channels ({len(channels)}):**\n{channels_str}\n\n"
        f"🔢 **Daily Sessions:** `{s.get('num_sessions')}`\n"
        f"⏰ **Session Timings (IST):** `{timings_str}`\n"
        f"🎯 **Trades per Session:** `{s.get('trades_per_session')}`\n"
        f"🔗 **Broker Link:** {s.get('login_link')}\n\n"
        f"✍️ **Closing Review Message:**\n_{s.get('closing_message')}_\n\n"
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

        _user_states.pop(message.chat.id, None)
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

        if data == "cancel_action" or data == "refresh_panel":
            _user_states.pop(chat_id, None)
            bot.edit_message_text(
                build_status_text(),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=get_admin_menu_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id, "Dashboard Ready!")

        elif data == "mgr_channels":
            _user_states.pop(chat_id, None)
            channels = get_channels()
            ch_list = "\n".join([f"• `{ch}`" for ch in channels]) if channels else "_No channels added yet._"
            msg = (
                "📢 **CHANNEL MANAGER**\n\n"
                f"**Active Target Channels:**\n{ch_list}\n\n"
                "• Tap **➕ Add Channel** to add a new Public/Private channel.\n"
                "• Tap **➖ Remove Channel** to delete an existing channel."
            )
            bot.edit_message_text(
                msg,
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=get_channel_manager_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "ch_add":
            _user_states[chat_id] = "WAITING_ADD_CHANNEL"
            msg = (
                "➕ **Add Target Channel**\n\n"
                "• For **Public Channel:** Send username (e.g. `@WebDealx`)\n"
                "• For **Private Channel:** Send channel ID (e.g. `-1001234567890`)\n\n"
                "⚠️ *Make sure the bot is added as Admin in the channel first!*"
            )
            bot.send_message(chat_id, msg, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "ch_remove_menu":
            channels = get_channels()
            if not channels:
                bot.answer_callback_query(call.id, "No channels to remove!", show_alert=True)
                return
            bot.edit_message_text(
                "🗑️ **Select a channel to remove:**",
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=get_remove_channels_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("delch_"):
            target_ch = data.replace("delch_", "")
            if remove_channel(target_ch):
                bot.answer_callback_query(call.id, f"Removed {target_ch}!", show_alert=True)
            else:
                bot.answer_callback_query(call.id, "Channel not found.")
            
            # Refresh remove menu or go back to manager
            channels = get_channels()
            if channels:
                bot.edit_message_text(
                    "🗑️ **Select a channel to remove:**",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    reply_markup=get_remove_channels_keyboard(),
                    parse_mode="Markdown"
                )
            else:
                bot.edit_message_text(
                    build_status_text(),
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    reply_markup=get_admin_menu_keyboard(),
                    parse_mode="Markdown"
                )

        elif data == "set_sessions":
            _user_states[chat_id] = "WAITING_SESSIONS"
            bot.send_message(
                chat_id,
                "🔢 Enter the **Number of Daily Sessions** (e.g. `2`, `3` or `4`):",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "set_timings":
            _user_states[chat_id] = "WAITING_TIMINGS"
            msg = (
                "⏰ **Set Session Timings (24-Hour IST Format)**\n\n"
                "Send comma-separated times:\n"
                "👉 Example: `14:00, 18:30, 21:00`"
            )
            bot.send_message(chat_id, msg, reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
            bot.answer_callback_query(call.id)

        elif data == "set_trades":
            _user_states[chat_id] = "WAITING_TRADES"
            bot.send_message(
                chat_id,
                "🎯 Enter the **Number of Trades per Session** (e.g. `5` or `8`):",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "set_link":
            _user_states[chat_id] = "WAITING_LINK"
            bot.send_message(
                chat_id,
                "🔗 Send the **Broker Registration / Login Link**:\n_(Posted in channels 10 mins before session)_",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "set_msg":
            _user_states[chat_id] = "WAITING_MSG"
            bot.send_message(
                chat_id,
                "✍️ Send the **Closing Review / Testimonial Message**:\n_(Posted in channels after session ends)_",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "start_now":
            if is_session_active():
                bot.answer_callback_query(call.id, "⚠️ A session is already active!", show_alert=True)
                return

            channels = get_channels()
            if not channels:
                bot.answer_callback_query(call.id, "❌ No target channels configured!", show_alert=True)
                return

            s = get_all_settings()
            tr = int(s.get("trades_per_session", 5))

            bot.answer_callback_query(call.id, "🚀 Launching instant test session...", show_alert=True)
            t = threading.Thread(target=run_session, args=(tr,), daemon=True)
            t.start()

            bot.send_message(
                chat_id,
                f"🚀 **Session launched instantly across {len(channels)} channel(s)!**",
                parse_mode="Markdown"
            )

    @bot.message_handler(func=lambda msg: msg.chat.id in _user_states and msg.chat.type == "private")
    def handle_admin_inputs(message: types.Message):
        chat_id = message.chat.id
        state = _user_states.pop(chat_id, None)
        text = message.text.strip()

        if state == "WAITING_ADD_CHANNEL":
            if add_channel(text):
                bot.send_message(chat_id, f"✅ **Added Target Channel:** `{text}`", parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"ℹ️ Channel `{text}` is already in the list.", parse_mode="Markdown")

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
            bot.send_message(chat_id, f"✅ **Closing Review Message updated!**", parse_mode="Markdown")

        # Display updated dashboard
        bot.send_message(chat_id, build_status_text(), reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown")
