import math
from typing import Any, Dict, List

import telebot
from telebot import types

from config import BOT_TOKEN, ADMIN_IDS, ALL_OTC_PAIRS
from database import (
    get_all_settings,
    update_setting,
    get_channels,
    add_channel,
    remove_channel,
    get_selected_pairs,
    toggle_pair_selection,
    is_pair_selected,
)
from scheduler import run_session, is_session_active
import threading

# Admin state memory for multi-step text inputs
_user_states: Dict[int, str] = {}

# Tracks each admin's current position inside the Pair Selector
# {"mode": "list" | "search", "page": int, "query": str}
_pair_nav_state: Dict[int, Dict[str, Any]] = {}

PAIRS_PER_PAGE = 10  # 5 rows x 2 pairs, matches the [pair][pair] x5 layout


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
    btn_pairs = types.InlineKeyboardButton("💱 Select Pairs", callback_data="mgr_pairs")
    btn_sessions = types.InlineKeyboardButton("🔢 No. of Sessions", callback_data="set_sessions")
    btn_timings = types.InlineKeyboardButton("⏰ Session Timings", callback_data="set_timings")
    btn_trades = types.InlineKeyboardButton("🎯 Trades per Session", callback_data="set_trades")
    btn_link = types.InlineKeyboardButton("🔗 Broker Login Link", callback_data="set_link")
    btn_msg = types.InlineKeyboardButton("✍️ Closing Messages", callback_data="set_msg")
    btn_reverse = types.InlineKeyboardButton("🔄 Toggle Reverse Strategy", callback_data="toggle_reverse")
    btn_start_now = types.InlineKeyboardButton("🚀 Start Session NOW (Test)", callback_data="start_now")
    btn_refresh = types.InlineKeyboardButton("🔄 Refresh Dashboard", callback_data="refresh_panel")

    markup.add(btn_channel_mgr, btn_pairs)
    markup.add(btn_sessions, btn_timings)
    markup.add(btn_trades, btn_link)
    markup.add(btn_msg, btn_reverse)
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


def get_closing_msg_keyboard() -> types.InlineKeyboardMarkup:
    """Sub-menu to edit the 3 sequential closing messages."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("✍️ Message 1", callback_data="set_msg_1"))
    markup.add(types.InlineKeyboardButton("✍️ Message 2", callback_data="set_msg_2"))
    markup.add(types.InlineKeyboardButton("✍️ Message 3", callback_data="set_msg_3"))
    markup.add(types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_panel"))
    return markup


# ---------------------------------------------------------------------------
# PAIR SELECTOR (Search + Pagination)
# ---------------------------------------------------------------------------

def _display_for_symbol(symbol: str) -> str:
    for p in ALL_OTC_PAIRS:
        if p["symbol"] == symbol:
            return p["display"]
    return symbol


def _pair_label(pair: Dict[str, Any]) -> str:
    mark = "✅" if is_pair_selected(pair["symbol"]) else "⬜"
    return f"{mark} {pair['display']}"


def search_pairs(query: str) -> List[Dict[str, Any]]:
    """Case-insensitive match on display name / symbol, ignoring spaces, '/' and 'OTC'."""
    q = query.strip().lower().replace(" ", "").replace("/", "").replace("otc", "")
    if not q:
        return []
    results = []
    for pair in ALL_OTC_PAIRS:
        norm_display = pair["display"].lower().replace(" ", "").replace("/", "").replace("(otc)", "").replace("otc", "")
        norm_symbol = pair["symbol"].lower().replace("_otc", "")
        if q in norm_display or q in norm_symbol:
            results.append(pair)
    return results


def get_pairs_page_keyboard(chat_id: int, page: int) -> types.InlineKeyboardMarkup:
    """[pair][pair] x5 rows -> [Search Pair] -> [Prev][Page][Next] -> [Back]"""
    total_pages = max(1, math.ceil(len(ALL_OTC_PAIRS) / PAIRS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    _pair_nav_state[chat_id] = {"mode": "list", "page": page, "query": ""}

    start = page * PAIRS_PER_PAGE
    page_pairs = ALL_OTC_PAIRS[start:start + PAIRS_PER_PAGE]

    markup = types.InlineKeyboardMarkup(row_width=2)
    row: List[types.InlineKeyboardButton] = []
    for pair in page_pairs:
        row.append(types.InlineKeyboardButton(_pair_label(pair), callback_data=f"tp_{pair['symbol']}"))
        if len(row) == 2:
            markup.row(*row)
            row = []
    if row:
        markup.row(*row)

    markup.row(types.InlineKeyboardButton("🔍 Search Pair", callback_data="pairs_search"))

    nav_row = []
    if page > 0:
        nav_row.append(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"pg_{page - 1}"))
    nav_row.append(types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(types.InlineKeyboardButton("Next Page ➡️", callback_data=f"pg_{page + 1}"))
    markup.row(*nav_row)

    markup.row(types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="refresh_panel"))
    return markup


def get_pairs_search_results_keyboard(chat_id: int, query: str) -> types.InlineKeyboardMarkup:
    _pair_nav_state[chat_id] = {"mode": "search", "page": 0, "query": query}
    matches = search_pairs(query)

    markup = types.InlineKeyboardMarkup(row_width=2)
    if not matches:
        markup.row(types.InlineKeyboardButton("😕 No pair found — try again", callback_data="noop"))
    else:
        row = []
        for pair in matches[:20]:
            row.append(types.InlineKeyboardButton(_pair_label(pair), callback_data=f"tp_{pair['symbol']}"))
            if len(row) == 2:
                markup.row(*row)
                row = []
        if row:
            markup.row(*row)

    markup.row(types.InlineKeyboardButton("🔍 New Search", callback_data="pairs_search"))
    markup.row(types.InlineKeyboardButton("🔙 Back to Pairs", callback_data="pairs_back_to_list"))
    return markup


def build_pairs_header_text(chat_id: int) -> str:
    selected = get_selected_pairs()
    nav = _pair_nav_state.get(chat_id, {"mode": "list", "page": 0, "query": ""})

    if nav["mode"] == "search":
        header = f"🔍 **Search Results for:** `{nav['query']}`\n\n"
    else:
        header = "💱 **SELECT SIGNAL PAIRS**\n\n"

    selected_str = ", ".join(_display_for_symbol(s) for s in selected) if selected else "_None_"
    return (
        header
        + f"✅ **Currently Selected ({len(selected)}):**\n{selected_str}\n\n"
        + "Tap a pair below to select / deselect it (any number of pairs allowed)."
    )


# ---------------------------------------------------------------------------
# DASHBOARD STATUS TEXT
# ---------------------------------------------------------------------------

def build_status_text() -> str:
    """Formats the current bot configuration settings for the dashboard."""
    s = get_all_settings()
    channels = get_channels()
    channels_str = "\n".join([f"  • `{ch}`" for ch in channels]) if channels else "  • _None configured_"
    timings_str = ", ".join(s.get("session_timings", []))
    session_status = "🟢 ACTIVE (Running)" if is_session_active() else "⚪ IDLE (Waiting for Schedule)"

    selected = get_selected_pairs()
    preview_syms = selected[:5]
    pairs_preview = ", ".join(_display_for_symbol(sym) for sym in preview_syms)
    if len(selected) > 5:
        pairs_preview += f" +{len(selected) - 5} more"
    reverse_on = bool(s.get("reverse_strategy", True))

    return (
        "⚙️ **POCKET OPTION VIP BOT — ADMIN DASHBOARD** ⚙️\n\n"
        f"📊 **Live Status:** {session_status}\n\n"
        f"📢 **Target Channels ({len(channels)}):**\n{channels_str}\n\n"
        f"💱 **Selected Pairs ({len(selected)}):** {pairs_preview}\n"
        f"🔄 **Reverse Strategy:** {'ON ✅ (channel shows opposite of raw signal)' if reverse_on else 'OFF ❌ (channel shows raw signal)'}\n"
        f"🔢 **Daily Sessions:** `{s.get('num_sessions')}`\n"
        f"⏰ **Session Timings (IST):** `{timings_str}`\n"
        f"🎯 **Trades per Session:** `{s.get('trades_per_session')}`\n"
        f"🔗 **Broker Link:** {s.get('login_link')}\n\n"
        f"✍️ **Closing Messages:** 3 set (2-min gap, end sticker 2 min after msg 3)\n\n"
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

        if data == "noop":
            bot.answer_callback_query(call.id)
            return

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

        # ---------------- PAIR SELECTOR ----------------

        elif data == "mgr_pairs":
            _user_states.pop(chat_id, None)
            markup = get_pairs_page_keyboard(chat_id, 0)
            bot.edit_message_text(
                build_pairs_header_text(chat_id),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("pg_"):
            page = int(data.replace("pg_", ""))
            markup = get_pairs_page_keyboard(chat_id, page)
            bot.edit_message_text(
                build_pairs_header_text(chat_id),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data == "pairs_back_to_list":
            markup = get_pairs_page_keyboard(chat_id, 0)
            bot.edit_message_text(
                build_pairs_header_text(chat_id),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data.startswith("tp_"):
            symbol = data.replace("tp_", "")
            now_selected = toggle_pair_selection(symbol)
            status_txt = "✅ Selected" if now_selected else "❌ Removed"
            bot.answer_callback_query(call.id, f"{status_txt}: {_display_for_symbol(symbol)}")

            nav = _pair_nav_state.get(chat_id, {"mode": "list", "page": 0, "query": ""})
            if nav["mode"] == "search":
                markup = get_pairs_search_results_keyboard(chat_id, nav["query"])
            else:
                markup = get_pairs_page_keyboard(chat_id, nav["page"])

            bot.edit_message_text(
                build_pairs_header_text(chat_id),
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )

        elif data == "pairs_search":
            _user_states[chat_id] = "WAITING_PAIR_SEARCH"
            bot.send_message(
                chat_id,
                "🔍 **Type the pair name to search** (e.g. `USD/JPY`, `usdjpy`, `AED`):",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        # ---------------- REVERSE STRATEGY ----------------

        elif data == "toggle_reverse":
            current = bool(get_all_settings().get("reverse_strategy", True))
            update_setting("reverse_strategy", not current)
            bot.answer_callback_query(
                call.id,
                f"Reverse Strategy is now {'ON' if not current else 'OFF'}!",
                show_alert=True
            )
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

        # ---------------- CLOSING MESSAGES (3-part) ----------------

        elif data == "set_msg":
            _user_states.pop(chat_id, None)
            s = get_all_settings()
            msg = (
                "✍️ **CLOSING MESSAGES**\n"
                "_(Sent one after another after the last trade, 2-min gap between each. "
                "End sticker fires 2 min after Message 3.)_\n\n"
                f"**1️⃣ Message 1:**\n_{s.get('closing_msg_1')}_\n\n"
                f"**2️⃣ Message 2:**\n_{s.get('closing_msg_2')}_\n\n"
                f"**3️⃣ Message 3:**\n_{s.get('closing_msg_3')}_\n\n"
                "👇 Tap a message number to edit it:"
            )
            bot.edit_message_text(
                msg,
                chat_id=chat_id,
                message_id=call.message.message_id,
                reply_markup=get_closing_msg_keyboard(),
                parse_mode="Markdown"
            )
            bot.answer_callback_query(call.id)

        elif data in ("set_msg_1", "set_msg_2", "set_msg_3"):
            idx = data[-1]
            _user_states[chat_id] = f"WAITING_MSG_{idx}"
            bot.send_message(
                chat_id,
                f"✍️ Send the new text for **Closing Message {idx}**:",
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
        text = message.text.strip() if message.text else ""

        # Pair search stays inside the Pair Selector UI, no dashboard refresh
        if state == "WAITING_PAIR_SEARCH":
            markup = get_pairs_search_results_keyboard(chat_id, text)
            bot.send_message(
                chat_id,
                build_pairs_header_text(chat_id),
                reply_markup=markup,
                parse_mode="Markdown"
            )
            return

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
            bot.send_message(chat_id, "✅ **Broker Login Link updated!**", parse_mode="Markdown")

        elif state in ("WAITING_MSG_1", "WAITING_MSG_2", "WAITING_MSG_3"):
            idx = state[-1]
            update_setting(f"closing_msg_{idx}", text)
            bot.send_message(chat_id, f"✅ **Closing Message {idx} updated!**", parse_mode="Markdown")

        # Display updated dashboard
        bot.send_message(chat_id, build_status_text(), reply_markup=get_admin_menu_keyboard(), parse_mode="Markdown")
